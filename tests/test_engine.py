"""Tests for the transcriber wrapper, using a stub model (no weights)."""

from __future__ import annotations

import pytest

from app.engine import EngineNotReady, Transcriber, get_transcriber, set_transcriber


class _StubSegment:
    def __init__(self, start, end, text, logprob=-0.1, nsp=0.01):
        self.start = start
        self.end = end
        self.text = text
        self.avg_logprob = logprob
        self.no_speech_prob = nsp


class _StubInfo:
    language = "en"
    language_probability = 0.97
    duration = 4.0


class _StubModel:
    def __init__(self, segments):
        self._segments = segments
        self.calls = []

    def transcribe(self, path, **kwargs):
        self.calls.append({"path": path, **kwargs})
        return iter(self._segments), _StubInfo()


class TestTranscriber:
    def test_missing_file_raises(self, tmp_path):
        t = Transcriber(model_name="tiny")
        with pytest.raises(FileNotFoundError):
            t.transcribe(tmp_path / "nope.wav")

    def test_transcribe_maps_segments(self, tmp_path):
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF")

        t = Transcriber(model_name="tiny")
        t._model = _StubModel(
            [
                _StubSegment(0.0, 1.0, " hello "),
                _StubSegment(1.0, 2.0, "world"),
            ]
        )

        result = t.transcribe(audio)
        assert result.text == "hello world"
        assert len(result.segments) == 2
        assert result.segments[0].index == 0
        assert result.segments[1].index == 1
        assert result.language == "en"
        assert result.duration_seconds == 4.0

    def test_blank_segments_are_dropped(self, tmp_path):
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF")

        t = Transcriber(model_name="tiny")
        t._model = _StubModel(
            [
                _StubSegment(0.0, 1.0, "real"),
                _StubSegment(1.0, 2.0, "   "),
                _StubSegment(2.0, 3.0, ""),
            ]
        )

        result = t.transcribe(audio)
        assert len(result.segments) == 1
        assert result.text == "real"

    def test_indices_are_contiguous_after_dropping(self, tmp_path):
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF")

        t = Transcriber(model_name="tiny")
        t._model = _StubModel(
            [
                _StubSegment(0.0, 1.0, "one"),
                _StubSegment(1.0, 2.0, ""),
                _StubSegment(2.0, 3.0, "three"),
            ]
        )

        result = t.transcribe(audio)
        assert [s.index for s in result.segments] == [0, 1]

    def test_language_passed_through(self, tmp_path):
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF")

        t = Transcriber(model_name="tiny")
        model = _StubModel([_StubSegment(0, 1, "x")])
        t._model = model

        t.transcribe(audio, language="ur")
        assert model.calls[0]["language"] == "ur"

    def test_vad_is_enabled(self, tmp_path):
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF")

        t = Transcriber(model_name="tiny")
        model = _StubModel([_StubSegment(0, 1, "x")])
        t._model = model

        t.transcribe(audio)
        assert model.calls[0]["vad_filter"] is True

    def test_is_ready_reflects_model(self):
        t = Transcriber(model_name="tiny")
        assert t.is_ready is False
        t._model = _StubModel([])
        assert t.is_ready is True

    def test_load_failure_raises_engine_not_ready(self, monkeypatch):
        t = Transcriber(model_name="definitely-not-a-real-model")

        def _boom(*args, **kwargs):
            raise RuntimeError("no such model")

        monkeypatch.setattr("faster_whisper.WhisperModel", _boom)
        with pytest.raises(EngineNotReady):
            t.load()
        assert t.load_error is not None


class TestSingleton:
    def test_get_returns_same_instance(self):
        set_transcriber(None)
        a = get_transcriber()
        b = get_transcriber()
        assert a is b
        set_transcriber(None)

    def test_set_replaces(self):
        custom = Transcriber(model_name="base")
        set_transcriber(custom)
        assert get_transcriber() is custom
        set_transcriber(None)
