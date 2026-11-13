"""Speech recognition engine.

Wraps faster-whisper behind a small, testable interface. The model is loaded
lazily and cached for the process lifetime, because loading it costs several
seconds and a few hundred MB of RAM.

Design notes
------------
* ``Transcriber`` is the only place that touches the model. Everything else
  (subtitle formatting, validation, persistence) is pure and unit-testable
  without downloading weights.
* The engine is CPU-first. ``compute_type="int8"`` keeps a tiny model under
  ~100 MB resident, which is what makes this runnable on a small VPS.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SegmentResult:
    """One timed chunk of recognised speech."""

    index: int
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None


@dataclass(slots=True)
class TranscriptionResult:
    """Everything the engine learned about one audio file."""

    text: str
    language: str | None
    language_probability: float | None
    duration_seconds: float | None
    model_name: str
    processing_ms: int
    segments: list[SegmentResult] = field(default_factory=list)


class EngineNotReady(RuntimeError):
    """Raised when the model cannot be loaded (missing deps, no weights)."""


class Transcriber:
    """Lazy, thread-safe wrapper around a faster-whisper model."""

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ) -> None:
        self.model_name = model_name or settings.whisper_model
        self.device = device or settings.whisper_device
        self.compute_type = compute_type or settings.whisper_compute_type
        self._model = None
        self._lock = threading.Lock()
        self._load_error: str | None = None

    # -- lifecycle ---------------------------------------------------------
    @property
    def is_ready(self) -> bool:
        """True once the model has been loaded successfully."""
        return self._model is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self):
        """Load the model once. Safe to call from multiple threads."""
        if self._model is not None:
            return self._model

        with self._lock:
            if self._model is not None:  # another thread won the race
                return self._model
            try:
                from faster_whisper import WhisperModel

                logger.info(
                    "Loading whisper model=%s device=%s compute=%s",
                    self.model_name,
                    self.device,
                    self.compute_type,
                )
                started = time.perf_counter()
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                )
                logger.info("Model loaded in %.1fs", time.perf_counter() - started)
                self._load_error = None
            except Exception as exc:  # noqa: BLE001 - surfaced to the caller
                self._load_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Failed to load whisper model")
                raise EngineNotReady(self._load_error) from exc
        return self._model

    # -- transcription -----------------------------------------------------
    def transcribe(
        self,
        audio_path: str | Path,
        language: str | None = None,
        beam_size: int | None = None,
    ) -> TranscriptionResult:
        """Transcribe one audio file.

        ``language=None`` lets the model detect it. Passing an ISO code
        (``"en"``, ``"ur"``, ``"ar"``) skips detection and is faster.
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"audio file not found: {path}")

        model = self.load()
        started = time.perf_counter()

        segments_iter, info = model.transcribe(
            str(path),
            language=language or None,
            beam_size=beam_size or settings.whisper_beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )

        # The generator is lazy: the actual work happens while iterating.
        segments: list[SegmentResult] = []
        for seg in segments_iter:
            text = (seg.text or "").strip()
            if not text:
                continue
            segments.append(
                SegmentResult(
                    index=len(segments),
                    start=round(float(seg.start), 3),
                    end=round(float(seg.end), 3),
                    text=text,
                    avg_logprob=getattr(seg, "avg_logprob", None),
                    no_speech_prob=getattr(seg, "no_speech_prob", None),
                )
            )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        full_text = " ".join(s.text for s in segments).strip()

        return TranscriptionResult(
            text=full_text,
            language=getattr(info, "language", None),
            language_probability=(
                round(float(info.language_probability), 4)
                if getattr(info, "language_probability", None) is not None
                else None
            ),
            duration_seconds=(
                round(float(info.duration), 3)
                if getattr(info, "duration", None) is not None
                else None
            ),
            model_name=self.model_name,
            processing_ms=elapsed_ms,
            segments=segments,
        )


# Process-wide singleton. Tests inject their own instance.
_transcriber: Transcriber | None = None


def get_transcriber() -> Transcriber:
    """Return the shared transcriber, creating it on first use."""
    global _transcriber
    if _transcriber is None:
        _transcriber = Transcriber()
    return _transcriber


def set_transcriber(instance: Transcriber | None) -> None:
    """Swap the singleton (used by tests)."""
    global _transcriber
    _transcriber = instance
