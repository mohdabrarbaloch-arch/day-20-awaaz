"""Shared pytest fixtures.

Tests run against an in-memory SQLite database and a fake transcriber, so
the suite is fast and never downloads model weights.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Must be set before app.config is imported anywhere.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_awaaz.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-32chars")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("UPLOAD_DIR", "./test_uploads")
os.environ.setdefault("BCRYPT_ROUNDS", "4")  # keep hashing fast in tests
# The suite registers a user per test, which would trip the real auth limit.
# Rate limiting itself is covered by its own test, not by accident here.
os.environ.setdefault("AUTH_RATE_LIMIT", "100000/minute")
os.environ.setdefault("RATE_LIMIT", "100000/minute")

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.engine import SegmentResult, TranscriptionResult, set_transcriber  # noqa: E402


class FakeTranscriber:
    """Stands in for the real model. Deterministic and instant."""

    def __init__(self, text: str = "hello world this is a test", fail: bool = False):
        self.model_name = "fake-tiny"
        self._text = text
        self._fail = fail
        self.calls = 0

    @property
    def is_ready(self) -> bool:
        return True

    @property
    def load_error(self):
        return None

    def load(self):
        return self

    def transcribe(self, audio_path, language=None, beam_size=None):
        self.calls += 1
        if self._fail:
            raise RuntimeError("simulated engine failure")

        words = self._text.split()
        half = max(1, len(words) // 2)
        first = " ".join(words[:half])
        second = " ".join(words[half:])

        segments = [
            SegmentResult(index=0, start=0.0, end=1.5, text=first, avg_logprob=-0.2),
            SegmentResult(index=1, start=1.5, end=3.0, text=second, avg_logprob=-0.3),
        ]
        return TranscriptionResult(
            text=self._text,
            language=language or "en",
            language_probability=0.98,
            duration_seconds=3.0,
            model_name=self.model_name,
            processing_ms=42,
            segments=segments,
        )


@pytest.fixture(autouse=True)
def _fresh_db():
    """Drop and recreate every table for each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def fake_transcriber():
    fake = FakeTranscriber()
    set_transcriber(fake)
    yield fake
    set_transcriber(None)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(fake_transcriber):
    """TestClient with the fake engine already installed."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth(client):
    """Register a user and return (headers, user_payload)."""
    res = client.post(
        "/api/auth/register",
        json={
            "email": "tester@example.com",
            "password": "supersecret123",
            "display_name": "Tester",
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]


@pytest.fixture
def wav_bytes() -> bytes:
    """A tiny but structurally valid WAV header (44 bytes, no samples)."""
    import struct

    data = b"\x00\x00" * 100
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data
