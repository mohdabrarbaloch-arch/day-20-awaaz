"""Tests for upload validation and filename safety."""

from __future__ import annotations

import pytest

from app.uploads import (
    UploadRejected,
    build_storage_path,
    detect_container,
    sanitize_filename,
    validate_upload,
)

WAV_HEAD = b"RIFF\x24\x00\x00\x00WAVEfmt "
MP3_HEAD = b"ID3\x04\x00\x00\x00\x00\x00\x00"
OGG_HEAD = b"OggS\x00\x02\x00\x00"
FLAC_HEAD = b"fLaC\x00\x00\x00\x22"
MP4_HEAD = b"\x00\x00\x00\x20ftypM4A "


class TestSanitizeFilename:
    def test_strips_directory_traversal(self):
        assert "/" not in sanitize_filename("../../etc/passwd")

    def test_windows_backslashes(self):
        assert "\\" not in sanitize_filename("..\\..\\windows\\system32")

    def test_keeps_extension(self):
        assert sanitize_filename("my audio.mp3").endswith(".mp3")

    def test_spaces_become_underscores(self):
        assert sanitize_filename("my audio file.mp3") == "my_audio_file.mp3"

    def test_unicode_is_transliterated(self):
        out = sanitize_filename("آواز.mp3")
        assert out.isascii()

    def test_empty_returns_fallback(self):
        assert sanitize_filename("") == "audio"

    def test_only_dots_returns_fallback(self):
        assert sanitize_filename("...") == "audio"

    def test_long_name_is_truncated(self):
        out = sanitize_filename("a" * 300 + ".mp3")
        assert len(out) <= 120
        assert out.endswith(".mp3")


class TestDetectContainer:
    def test_wav(self):
        assert detect_container(WAV_HEAD) == "wav"

    def test_mp3_id3(self):
        assert detect_container(MP3_HEAD) == "mp3"

    def test_ogg(self):
        assert detect_container(OGG_HEAD) == "ogg"

    def test_flac(self):
        assert detect_container(FLAC_HEAD) == "flac"

    def test_mp4(self):
        assert detect_container(MP4_HEAD) == "mp4"

    def test_riff_that_is_not_wave(self):
        # RIFF/AVI must not be mistaken for audio.
        assert detect_container(b"RIFF\x00\x00\x00\x00AVI ") is None

    def test_garbage(self):
        assert detect_container(b"this is not audio at all") is None

    def test_empty(self):
        assert detect_container(b"") is None


class TestValidateUpload:
    def test_accepts_valid_wav(self):
        name = validate_upload("talk.wav", "audio/wav", 1000, WAV_HEAD)
        assert name == "talk.wav"

    def test_rejects_empty_file(self):
        with pytest.raises(UploadRejected, match="empty"):
            validate_upload("talk.wav", "audio/wav", 0, WAV_HEAD)

    def test_rejects_oversized(self):
        with pytest.raises(UploadRejected, match="too large"):
            validate_upload("talk.wav", "audio/wav", 999 * 1024 * 1024, WAV_HEAD)

    def test_rejects_wrong_content_type(self):
        with pytest.raises(UploadRejected, match="Unsupported content type"):
            validate_upload("evil.exe", "application/x-msdownload", 1000, WAV_HEAD)

    def test_rejects_non_audio_bytes(self):
        with pytest.raises(UploadRejected, match="does not look like audio"):
            validate_upload("fake.mp3", "audio/mpeg", 1000, b"PK\x03\x04zipfile")

    def test_rejects_extension_mismatch(self):
        # Claims to be FLAC, is actually a WAV.
        with pytest.raises(UploadRejected, match="does not match"):
            validate_upload("song.flac", "audio/flac", 1000, WAV_HEAD)

    def test_accepts_m4a_as_mp4(self):
        name = validate_upload("voice.m4a", "audio/mp4", 1000, MP4_HEAD)
        assert name == "voice.m4a"


class TestBuildStoragePath:
    def test_creates_user_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.uploads.settings.upload_dir", str(tmp_path))
        path = build_storage_path("audio.mp3", user_id=7)
        assert path.parent.name == "u7"
        assert path.parent.exists()

    def test_stored_name_is_uuid_not_original(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.uploads.settings.upload_dir", str(tmp_path))
        path = build_storage_path("my secret recording.mp3", user_id=1)
        assert "secret" not in path.name
        assert path.suffix == ".mp3"

    def test_two_uploads_do_not_collide(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.uploads.settings.upload_dir", str(tmp_path))
        a = build_storage_path("same.mp3", user_id=1)
        b = build_storage_path("same.mp3", user_id=1)
        assert a != b

    def test_stays_inside_upload_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.uploads.settings.upload_dir", str(tmp_path))
        path = build_storage_path("../../escape.mp3", user_id=1)
        assert str(path).startswith(str(tmp_path.resolve()))
