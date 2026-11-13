"""Subtitle and transcript formatting.

All functions here are pure: they take segments and return a string. That
makes them cheap to test and impossible to get wrong at runtime because of
I/O. Timestamp maths is the fiddly part, so it lives in one place.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Cue:
    """A minimal subtitle cue: start, end, text."""

    start: float
    end: float
    text: str


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def format_timestamp(seconds: float, *, comma: bool = True) -> str:
    """Format seconds as ``HH:MM:SS,mmm`` (SRT) or ``HH:MM:SS.mmm`` (VTT).

    Negative values clamp to zero. Hours are not capped at 24 — a long
    recording should read ``25:00:00`` rather than wrapping.
    """
    if seconds is None or seconds != seconds:  # None or NaN
        seconds = 0.0
    total_ms = int(round(_clamp(float(seconds), 0.0, 359_999.999) * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    sep = "," if comma else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{millis:03d}"


def to_srt(cues: Sequence[Cue]) -> str:
    """Render cues as SubRip (.srt)."""
    blocks: list[str] = []
    for i, cue in enumerate(cues, start=1):
        start = format_timestamp(cue.start, comma=True)
        end = format_timestamp(cue.end, comma=True)
        text = cue.text.strip()
        if not text:
            continue
        blocks.append(f"{i}\n{start} --> {end}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def to_vtt(cues: Sequence[Cue]) -> str:
    """Render cues as WebVTT (.vtt)."""
    lines: list[str] = ["WEBVTT", ""]
    for cue in cues:
        start = format_timestamp(cue.start, comma=False)
        end = format_timestamp(cue.end, comma=False)
        text = cue.text.strip()
        if not text:
            continue
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def to_txt(cues: Sequence[Cue], *, timestamps: bool = False) -> str:
    """Plain text, optionally prefixed with ``[MM:SS]`` markers."""
    if not timestamps:
        return " ".join(c.text.strip() for c in cues if c.text.strip()).strip() + "\n"

    out: list[str] = []
    for cue in cues:
        text = cue.text.strip()
        if not text:
            continue
        total = int(cue.start)
        minutes, secs = divmod(total, 60)
        out.append(f"[{minutes:02d}:{secs:02d}] {text}")
    return "\n".join(out) + ("\n" if out else "")


def to_markdown(cues: Sequence[Cue], *, title: str = "Transcript") -> str:
    """A readable markdown transcript with timestamped paragraphs."""
    lines = [f"# {title}", ""]
    for cue in cues:
        text = cue.text.strip()
        if not text:
            continue
        total = int(cue.start)
        minutes, secs = divmod(total, 60)
        lines.append(f"**{minutes:02d}:{secs:02d}** — {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def cues_from_segments(segments: Iterable) -> list[Cue]:
    """Adapt ORM/engine segments into plain cues.

    Accepts anything with ``start``, ``end`` and ``text`` attributes, which
    covers both ``SegmentResult`` and the ``Segment`` ORM model.
    """
    cues: list[Cue] = []
    for seg in segments:
        start = float(getattr(seg, "start", 0.0) or 0.0)
        end = float(getattr(seg, "end", start) or start)
        if end < start:
            end = start
        cues.append(Cue(start=start, end=end, text=str(getattr(seg, "text", "") or "")))
    return cues


def merge_short_cues(cues: Sequence[Cue], *, min_duration: float = 1.0) -> list[Cue]:
    """Extend cues that are too short to read.

    Whisper sometimes emits a 0.2s cue for a whole sentence, which flashes
    past unreadably. We stretch the end, but never past the next cue's start.
    """
    merged: list[Cue] = []
    for i, cue in enumerate(cues):
        end = cue.end
        if end - cue.start < min_duration:
            limit = cues[i + 1].start if i + 1 < len(cues) else cue.start + min_duration
            end = max(end, min(cue.start + min_duration, limit))
        merged.append(Cue(start=cue.start, end=end, text=cue.text))
    return merged


EXPORT_FORMATS = ("txt", "srt", "vtt", "md")


def render(cues: Sequence[Cue], fmt: str, *, title: str = "Transcript") -> str:
    """Dispatch to the right renderer. Raises ``ValueError`` on unknown fmt."""
    fmt = (fmt or "").lower().strip()
    if fmt == "txt":
        return to_txt(cues)
    if fmt == "srt":
        return to_srt(cues)
    if fmt == "vtt":
        return to_vtt(cues)
    if fmt in {"md", "markdown"}:
        return to_markdown(cues, title=title)
    raise ValueError(f"unsupported format: {fmt!r} (expected one of {EXPORT_FORMATS})")
