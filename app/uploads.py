"""Upload validation and safe file handling.

Two jobs: reject anything that is not plausibly audio before we spend CPU on
it, and make sure a hostile filename can never escape the upload directory.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from pathlib import Path

from app.config import settings

# Magic-number prefixes for the containers we accept. Extension alone is not
# evidence — a .mp3 that is really a zip should be refused.
# RIFF is deliberately absent: it is also the container for AVI video, so a
# bare RIFF prefix is not evidence of audio. WAV is matched on the form type
# in ``detect_container`` instead.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"ID3", "mp3"),  # MP3 with ID3 tag
    (b"\xff\xfb", "mp3"),  # MP3 frame sync
    (b"\xff\xf3", "mp3"),
    (b"\xff\xf2", "mp3"),
    (b"OggS", "ogg"),  # Ogg / Opus
    (b"fLaC", "flac"),  # FLAC
    (b"\x1aE\xdf\xa3", "webm"),  # Matroska / WebM
    (b"ftyp", "mp4"),  # MP4 / M4A (offset 4)
)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class UploadRejected(ValueError):
    """Raised when an upload fails validation. Message is user-facing."""


def sanitize_filename(name: str, *, max_length: int = 120) -> str:
    """Reduce an arbitrary filename to something safe to store.

    Strips directory components, normalises unicode, and keeps only a
    conservative character set. Never returns an empty string.
    """
    if not name:
        return "audio"

    # Take the basename only — defeats "../../etc/passwd".
    base = Path(name.replace("\\", "/")).name
    base = unicodedata.normalize("NFKD", base)
    base = base.encode("ascii", "ignore").decode("ascii")
    base = _SAFE_NAME.sub("_", base).strip("._-")

    if not base:
        return "audio"

    if len(base) > max_length:
        stem, dot, ext = base.rpartition(".")
        if dot and len(ext) <= 8:
            keep = max_length - len(ext) - 1
            base = f"{stem[:keep]}.{ext}"
        else:
            base = base[:max_length]

    return base or "audio"


def detect_container(head: bytes) -> str | None:
    """Best-effort container sniff from the first bytes of a file."""
    if not head:
        return None

    if head[:4] == b"RIFF" and len(head) >= 12 and head[8:12] == b"WAVE":
        return "wav"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mp4"
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    return None


def validate_upload(
    filename: str,
    content_type: str | None,
    size_bytes: int,
    head: bytes,
) -> str:
    """Validate an upload and return the sanitized filename.

    Raises ``UploadRejected`` with a message safe to show the user.
    """
    if size_bytes <= 0:
        raise UploadRejected("The file is empty.")

    if size_bytes > settings.max_upload_bytes:
        raise UploadRejected(f"File is too large. The limit is {settings.max_upload_mb} MB.")

    safe_name = sanitize_filename(filename)
    suffix = Path(safe_name).suffix.lower().lstrip(".")

    declared = (content_type or "").split(";")[0].strip().lower()
    if declared and declared not in settings.allowed_types:
        raise UploadRejected(
            f"Unsupported content type {declared!r}. Upload an audio or video file."
        )

    container = detect_container(head)
    if container is None:
        raise UploadRejected(
            "That file does not look like audio or video. "
            "Supported: wav, mp3, m4a, ogg, flac, webm, mp4."
        )

    # A declared type that disagrees with the bytes is a red flag, but some
    # browsers send generic types, so only reject when both are specific.
    _AUDIO_SUFFIXES = {"wav", "mp3", "m4a", "ogg", "flac", "webm", "mp4"}
    if declared and declared.startswith(("audio/", "video/")) and suffix in _AUDIO_SUFFIXES:
        if suffix == "m4a" and container != "mp4":
            raise UploadRejected("File extension does not match its contents.")
        if suffix in {"wav", "mp3", "ogg", "flac", "webm"} and suffix != container:
            raise UploadRejected("File extension does not match its contents.")

    return safe_name


def build_storage_path(original_name: str, *, user_id: int) -> Path:
    """Return a collision-free path inside the upload directory.

    The stored name is a UUID, so two users uploading ``audio.mp3`` never
    overwrite each other and the original name is never trusted on disk.
    """
    root = Path(settings.upload_dir).resolve()
    user_dir = root / f"u{int(user_id)}"
    user_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(sanitize_filename(original_name)).suffix.lower() or ".bin"
    if len(suffix) > 10:
        suffix = ".bin"

    target = (user_dir / f"{uuid.uuid4().hex}{suffix}").resolve()

    # Belt and braces: the resolved path must stay under the upload root.
    if not str(target).startswith(str(root)):
        raise UploadRejected("Invalid upload path.")

    return target
