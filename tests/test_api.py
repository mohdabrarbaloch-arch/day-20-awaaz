"""End-to-end API tests: auth, upload, transcription, export, ownership."""

from __future__ import annotations


class TestAuth:
    def test_register_returns_token(self, client):
        res = client.post(
            "/api/auth/register",
            json={"email": "a@b.com", "password": "password123", "display_name": "A"},
        )
        assert res.status_code == 201
        body = res.json()
        assert body["access_token"]
        assert body["user"]["email"] == "a@b.com"

    def test_duplicate_email_conflicts(self, client):
        payload = {"email": "dup@b.com", "password": "password123"}
        assert client.post("/api/auth/register", json=payload).status_code == 201
        assert client.post("/api/auth/register", json=payload).status_code == 409

    def test_weak_password_rejected(self, client):
        res = client.post(
            "/api/auth/register",
            json={"email": "weak@b.com", "password": "onlyletters"},
        )
        assert res.status_code == 422

    def test_short_password_rejected(self, client):
        res = client.post("/api/auth/register", json={"email": "s@b.com", "password": "a1"})
        assert res.status_code == 422

    def test_invalid_email_rejected(self, client):
        res = client.post(
            "/api/auth/register", json={"email": "not-an-email", "password": "abc12345"}
        )
        assert res.status_code == 422

    def test_login_succeeds(self, client, auth):
        res = client.post(
            "/api/auth/login",
            json={"email": "tester@example.com", "password": "supersecret123"},
        )
        assert res.status_code == 200
        assert res.json()["access_token"]

    def test_login_wrong_password(self, client, auth):
        res = client.post(
            "/api/auth/login",
            json={"email": "tester@example.com", "password": "wrongpassword1"},
        )
        assert res.status_code == 401

    def test_login_unknown_email_same_message(self, client, auth):
        res = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "whatever123"},
        )
        assert res.status_code == 401
        # Must not reveal whether the account exists.
        assert res.json()["detail"] == "Incorrect email or password."

    def test_me_requires_token(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_me_with_bad_token(self, client):
        res = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
        assert res.status_code == 401

    def test_me_returns_user(self, client, auth):
        headers, user = auth
        res = client.get("/api/auth/me", headers=headers)
        assert res.status_code == 200
        assert res.json()["id"] == user["id"]


class TestUpload:
    def test_requires_auth(self, client, wav_bytes):
        res = client.post(
            "/api/transcriptions",
            files={"file": ("a.wav", wav_bytes, "audio/wav")},
        )
        assert res.status_code == 401

    def test_upload_queues_and_completes(self, client, auth, wav_bytes):
        headers, _ = auth
        res = client.post(
            "/api/transcriptions",
            headers=headers,
            files={"file": ("talk.wav", wav_bytes, "audio/wav")},
        )
        assert res.status_code == 202
        body = res.json()
        assert body["status"] in {"queued", "processing", "completed"}
        assert body["original_name"] == "talk.wav"

    def test_rejects_non_audio(self, client, auth):
        headers, _ = auth
        res = client.post(
            "/api/transcriptions",
            headers=headers,
            files={"file": ("evil.mp3", b"PK\x03\x04not audio", "audio/mpeg")},
        )
        assert res.status_code == 422

    def test_rejects_empty_file(self, client, auth):
        headers, _ = auth
        res = client.post(
            "/api/transcriptions",
            headers=headers,
            files={"file": ("empty.wav", b"", "audio/wav")},
        )
        assert res.status_code == 422

    def test_rejects_wrong_content_type(self, client, auth, wav_bytes):
        headers, _ = auth
        res = client.post(
            "/api/transcriptions",
            headers=headers,
            files={"file": ("x.exe", wav_bytes, "application/x-msdownload")},
        )
        assert res.status_code == 422


class TestTranscriptionFlow:
    def _upload(self, client, headers, wav_bytes, name="talk.wav"):
        res = client.post(
            "/api/transcriptions",
            headers=headers,
            files={"file": (name, wav_bytes, "audio/wav")},
        )
        assert res.status_code == 202, res.text
        return res.json()["id"]

    def test_completed_transcript_has_text(self, client, auth, wav_bytes):
        headers, _ = auth
        tid = self._upload(client, headers, wav_bytes)

        res = client.get(f"/api/transcriptions/{tid}", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "completed"
        assert body["text"] == "hello world this is a test"
        assert body["language"] == "en"
        assert len(body["segments"]) == 2

    def test_segments_are_ordered(self, client, auth, wav_bytes):
        headers, _ = auth
        tid = self._upload(client, headers, wav_bytes)
        body = client.get(f"/api/transcriptions/{tid}", headers=headers).json()
        starts = [s["start"] for s in body["segments"]]
        assert starts == sorted(starts)

    def test_list_is_paginated(self, client, auth, wav_bytes):
        headers, _ = auth
        for i in range(3):
            self._upload(client, headers, wav_bytes, name=f"f{i}.wav")

        res = client.get("/api/transcriptions?limit=2", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2
        assert body["limit"] == 2

    def test_list_rejects_bad_limit(self, client, auth):
        headers, _ = auth
        assert client.get("/api/transcriptions?limit=999", headers=headers).status_code == 422

    def test_export_srt(self, client, auth, wav_bytes):
        headers, _ = auth
        tid = self._upload(client, headers, wav_bytes)
        res = client.get(f"/api/transcriptions/{tid}/export?fmt=srt", headers=headers)
        assert res.status_code == 200
        assert "-->" in res.text
        assert "attachment" in res.headers["content-disposition"]

    def test_export_vtt(self, client, auth, wav_bytes):
        headers, _ = auth
        tid = self._upload(client, headers, wav_bytes)
        res = client.get(f"/api/transcriptions/{tid}/export?fmt=vtt", headers=headers)
        assert res.status_code == 200
        assert res.text.startswith("WEBVTT")

    def test_export_txt(self, client, auth, wav_bytes):
        headers, _ = auth
        tid = self._upload(client, headers, wav_bytes)
        res = client.get(f"/api/transcriptions/{tid}/export?fmt=txt", headers=headers)
        assert res.status_code == 200
        assert "hello world" in res.text

    def test_export_bad_format_rejected(self, client, auth, wav_bytes):
        headers, _ = auth
        tid = self._upload(client, headers, wav_bytes)
        res = client.get(f"/api/transcriptions/{tid}/export?fmt=exe", headers=headers)
        assert res.status_code == 422

    def test_delete_removes_record(self, client, auth, wav_bytes):
        headers, _ = auth
        tid = self._upload(client, headers, wav_bytes)
        assert client.delete(f"/api/transcriptions/{tid}", headers=headers).status_code == 204
        assert client.get(f"/api/transcriptions/{tid}", headers=headers).status_code == 404


class TestOwnership:
    def test_other_users_transcript_is_404_not_403(self, client, auth, wav_bytes):
        """A request must not be able to confirm someone else's record exists."""
        headers_a, _ = auth
        res = client.post(
            "/api/transcriptions",
            headers=headers_a,
            files={"file": ("mine.wav", wav_bytes, "audio/wav")},
        )
        tid = res.json()["id"]

        reg = client.post(
            "/api/auth/register",
            json={"email": "other@example.com", "password": "otherpass123"},
        )
        headers_b = {"Authorization": f"Bearer {reg.json()['access_token']}"}

        assert client.get(f"/api/transcriptions/{tid}", headers=headers_b).status_code == 404
        assert client.delete(f"/api/transcriptions/{tid}", headers=headers_b).status_code == 404
        assert (
            client.get(f"/api/transcriptions/{tid}/export?fmt=txt", headers=headers_b).status_code
            == 404
        )

    def test_list_only_shows_own(self, client, auth, wav_bytes):
        headers_a, _ = auth
        client.post(
            "/api/transcriptions",
            headers=headers_a,
            files={"file": ("mine.wav", wav_bytes, "audio/wav")},
        )

        reg = client.post(
            "/api/auth/register",
            json={"email": "second@example.com", "password": "secondpass123"},
        )
        headers_b = {"Authorization": f"Bearer {reg.json()['access_token']}"}

        body = client.get("/api/transcriptions", headers=headers_b).json()
        assert body["total"] == 0


class TestHealth:
    def test_health_is_public(self, client):
        res = client.get("/api/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["engine_ready"] is True

    def test_security_headers_present(self, client):
        res = client.get("/api/health")
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        assert res.headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in res.headers
