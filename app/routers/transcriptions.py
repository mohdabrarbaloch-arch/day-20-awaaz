"""Transcription routes: upload, list, detail, export, delete.

Note: this module deliberately does NOT use ``from __future__ import
annotations``. FastAPI resolves endpoint signatures at import time, and
postponed annotations turn ``UploadFile`` into a ForwardRef it cannot
resolve, which fails at startup rather than at request time.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db import SessionLocal, get_db
from app.engine import EngineNotReady, get_transcriber
from app.limiter import limiter
from app.models import JobStatus, Segment, Transcription, User
from app.schemas import TranscriptionDetail, TranscriptionList, TranscriptionOut
from app.security import get_current_user
from app.subtitles import cues_from_segments, merge_short_cues, render
from app.uploads import UploadRejected, build_storage_path, validate_upload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/transcriptions", tags=["transcriptions"])

_CHUNK = 1024 * 1024  # 1 MiB


def _owned(db: Session, transcription_id: int, user: User) -> Transcription:
    """Fetch a transcription the user owns, or 404.

    Deliberately 404 rather than 403: a request should not be able to
    confirm that someone else's record exists.
    """
    row = db.scalar(
        select(Transcription)
        .options(selectinload(Transcription.segments))
        .where(
            Transcription.id == transcription_id,
            Transcription.user_id == user.id,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found.",
        )
    return row


def _run_transcription(transcription_id: int) -> None:
    """Background job: transcribe one file and persist the result.

    Opens its own session because the request's session is closed by the
    time this runs.
    """
    db = SessionLocal()
    try:
        row = db.get(Transcription, transcription_id)
        if row is None:
            logger.warning("Transcription %s vanished before processing", transcription_id)
            return

        row.status = JobStatus.PROCESSING
        db.commit()

        try:
            result = get_transcriber().transcribe(row.stored_path)
        except EngineNotReady as exc:
            row.status = JobStatus.FAILED
            row.error = f"Speech engine unavailable: {exc}"
            db.commit()
            logger.error("Engine not ready for %s: %s", transcription_id, exc)
            return
        except Exception as exc:  # noqa: BLE001 - job must not crash the worker
            row.status = JobStatus.FAILED
            row.error = f"Transcription failed: {type(exc).__name__}"
            db.commit()
            logger.exception("Transcription %s failed", transcription_id)
            return

        row.text = result.text
        row.language = result.language
        row.language_probability = result.language_probability
        row.duration_seconds = result.duration_seconds
        row.model_name = result.model_name
        row.processing_ms = result.processing_ms
        row.status = JobStatus.COMPLETED
        row.completed_at = datetime.now(UTC)
        row.error = None

        for seg in result.segments:
            db.add(
                Segment(
                    transcription_id=row.id,
                    index=seg.index,
                    start=seg.start,
                    end=seg.end,
                    text=seg.text,
                    avg_logprob=seg.avg_logprob,
                    no_speech_prob=seg.no_speech_prob,
                )
            )

        db.commit()
        logger.info(
            "Transcription %s done in %sms (%s segments)",
            transcription_id,
            result.processing_ms,
            len(result.segments),
        )
    finally:
        db.close()


@router.post("", response_model=TranscriptionOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.rate_limit)
async def create_transcription(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    language: str | None = Query(
        default=None,
        max_length=8,
        description="ISO language code to skip detection, e.g. 'en' or 'ur'.",
    ),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> TranscriptionOut:
    """Accept an audio file and queue it for transcription.

    Returns 202 immediately with a ``queued`` record; poll the detail
    endpoint (or watch the UI) for the result.
    """
    head = await file.read(64)
    await file.seek(0)

    # Size is checked while streaming below, but reject obvious cases early.
    declared_size = getattr(file, "size", None) or 0
    if declared_size and declared_size > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File is too large. The limit is {settings.max_upload_mb} MB.",
        )

    try:
        safe_name = validate_upload(
            filename=file.filename or "audio",
            content_type=file.content_type,
            size_bytes=declared_size or len(head),
            head=head,
        )
        target = build_storage_path(safe_name, user_id=current.id)
    except UploadRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Stream to disk, enforcing the cap as we go so a lying Content-Length
    # cannot fill the volume.
    written = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise UploadRejected(
                        f"File is too large. The limit is {settings.max_upload_mb} MB."
                    )
                out.write(chunk)
    except UploadRejected as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    if written == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The file is empty.",
        )

    row = Transcription(
        user_id=current.id,
        original_name=safe_name,
        stored_path=str(target),
        content_type=(file.content_type or "")[:120],
        size_bytes=written,
        status=JobStatus.QUEUED,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    background.add_task(_run_transcription, row.id)
    return TranscriptionOut.model_validate(row)


@router.get("", response_model=TranscriptionList)
@limiter.limit(settings.rate_limit)
def list_transcriptions(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> TranscriptionList:
    """Paginated history, newest first."""
    total = (
        db.scalar(select(func.count(Transcription.id)).where(Transcription.user_id == current.id))
        or 0
    )

    rows = db.scalars(
        select(Transcription)
        .where(Transcription.user_id == current.id)
        .order_by(Transcription.created_at.desc(), Transcription.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return TranscriptionList(
        items=[TranscriptionOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{transcription_id}", response_model=TranscriptionDetail)
@limiter.limit(settings.rate_limit)
def get_transcription(
    request: Request,
    transcription_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> TranscriptionDetail:
    """Full record including timed segments."""
    row = _owned(db, transcription_id, current)
    return TranscriptionDetail.model_validate(row)


@router.get("/{transcription_id}/export", response_class=PlainTextResponse)
@limiter.limit(settings.rate_limit)
def export_transcription(
    request: Request,
    transcription_id: int,
    fmt: str = Query(default="txt", pattern="^(txt|srt|vtt|md|markdown)$"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PlainTextResponse:
    """Download the transcript as txt, srt, vtt or markdown."""
    row = _owned(db, transcription_id, current)

    if row.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transcription is {row.status.value}, not ready to export.",
        )

    cues = merge_short_cues(cues_from_segments(row.segments))
    body = render(cues, fmt, title=row.original_name)

    stem = Path(row.original_name).stem or "transcript"
    media = {
        "txt": "text/plain; charset=utf-8",
        "srt": "application/x-subrip; charset=utf-8",
        "vtt": "text/vtt; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "markdown": "text/markdown; charset=utf-8",
    }[fmt]
    ext = "md" if fmt == "markdown" else fmt

    return PlainTextResponse(
        content=body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{stem}.{ext}"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("/{transcription_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.rate_limit)
def delete_transcription(
    request: Request,
    transcription_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> None:
    """Delete a transcription, its segments and the stored audio file."""
    row = _owned(db, transcription_id, current)
    stored = row.stored_path

    db.delete(row)
    db.commit()

    # Best effort: a missing file is not an error worth failing the request.
    try:
        Path(stored).unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove stored file %s", stored)


@router.post("/{transcription_id}/retry", response_model=TranscriptionOut)
@limiter.limit(settings.rate_limit)
def retry_transcription(
    request: Request,
    transcription_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> TranscriptionOut:
    """Re-run a failed job without re-uploading the file."""
    row = _owned(db, transcription_id, current)

    if row.status in {JobStatus.QUEUED, JobStatus.PROCESSING}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This transcription is already in progress.",
        )
    if not Path(row.stored_path).exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The original audio file is no longer available.",
        )

    row.status = JobStatus.QUEUED
    row.error = None
    row.text = ""
    row.completed_at = None
    for seg in list(row.segments):
        db.delete(seg)
    db.commit()
    db.refresh(row)

    background.add_task(_run_transcription, row.id)
    return TranscriptionOut.model_validate(row)
