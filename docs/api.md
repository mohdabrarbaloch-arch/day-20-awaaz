# API Reference

Base URL: `http://127.0.0.1:8000`

Interactive docs: `/api/docs` · OpenAPI JSON: `/api/openapi.json`

All transcription routes require `Authorization: Bearer <token>`.

---

## Authentication

### `POST /api/auth/register`

Create an account. Returns a token so the client can go straight in.

**Body**

```json
{
  "email": "you@example.com",
  "password": "supersecret123",
  "display_name": "Your Name"
}
```

`password` must be 8–128 characters and mix letters with numbers.
`display_name` is optional and defaults to the local part of the email.

**Responses**

| Code | Meaning |
|---|---|
| `201` | Created — body is a `Token` |
| `409` | Email already registered |
| `422` | Validation failed (weak password, bad email) |
| `429` | Rate limited |

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "email": "you@example.com",
    "display_name": "Your Name",
    "created_at": "2026-11-14T00:12:00Z"
  }
}
```

---

### `POST /api/auth/login`

**Body**

```json
{ "email": "you@example.com", "password": "supersecret123" }
```

| Code | Meaning |
|---|---|
| `200` | `Token` |
| `401` | Wrong email or password — same message either way |
| `403` | Account disabled |
| `429` | Rate limited |

---

### `GET /api/auth/me`

Returns the authenticated `User`.

| Code | Meaning |
|---|---|
| `200` | `User` |
| `401` | Missing, malformed or expired token |

---

## Transcriptions

### `POST /api/transcriptions`

Upload audio and queue it. Returns immediately — the work happens in the
background.

**Query**

| Param | Type | Notes |
|---|---|---|
| `language` | string, optional | ISO code (`en`, `ur`, `hi`, `ar`, …). Omit to auto-detect. |

**Body** — `multipart/form-data`, field name `file`.

**Responses**

| Code | Meaning |
|---|---|
| `202` | Accepted — body is a `Transcription` with `status: "queued"` |
| `401` | Not authenticated |
| `413` | File exceeds `MAX_UPLOAD_MB` |
| `422` | Empty file, wrong MIME type, or bytes are not audio |
| `429` | Rate limited |

```bash
curl -X POST http://127.0.0.1:8000/api/transcriptions \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@interview.mp3" \
  -F "language=en"
```

---

### `GET /api/transcriptions`

Paginated history, newest first.

**Query**

| Param | Default | Range |
|---|---|---|
| `limit` | 20 | 1–100 |
| `offset` | 0 | ≥ 0 |

```json
{
  "items": [ { "id": 3, "status": "completed", "text": "…" } ],
  "total": 12,
  "limit": 20,
  "offset": 0
}
```

---

### `GET /api/transcriptions/{id}`

Full record including timed segments.

| Code | Meaning |
|---|---|
| `200` | `TranscriptionDetail` |
| `404` | Not found **or not yours** — deliberately indistinguishable |

```json
{
  "id": 3,
  "original_name": "interview.mp3",
  "status": "completed",
  "text": "hello world this is a test",
  "language": "en",
  "language_probability": 0.98,
  "duration_seconds": 3.0,
  "model_name": "tiny",
  "processing_ms": 42,
  "created_at": "2026-11-14T00:12:00Z",
  "completed_at": "2026-11-14T00:12:01Z",
  "segments": [
    { "index": 0, "start": 0.0, "end": 1.5, "text": "hello world", "avg_logprob": -0.2 },
    { "index": 1, "start": 1.5, "end": 3.0, "text": "this is a test", "avg_logprob": -0.3 }
  ]
}
```

---

### `GET /api/transcriptions/{id}/export`

Download the transcript.

**Query**

| Param | Values |
|---|---|
| `fmt` | `txt` · `srt` · `vtt` · `md` (or `markdown`) |

| Code | Meaning |
|---|---|
| `200` | File body with `Content-Disposition: attachment` |
| `404` | Not found or not yours |
| `409` | Job is not `completed` yet |
| `422` | Unknown format |

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/transcriptions/3/export?fmt=vtt" -o talk.vtt
```

---

### `POST /api/transcriptions/{id}/retry`

Re-run a failed job from the stored file.

| Code | Meaning |
|---|---|
| `200` | Requeued — body is the updated `Transcription` |
| `404` | Not found or not yours |
| `409` | Already queued or processing |
| `410` | The original audio file is gone |

---

### `DELETE /api/transcriptions/{id}`

Delete the record, its segments and the stored audio.

| Code | Meaning |
|---|---|
| `204` | Deleted |
| `404` | Not found or not yours |

---

## Meta

### `GET /api/health`

Public. No auth.

```json
{
  "status": "ok",
  "engine_ready": true,
  "model": "tiny",
  "version": "1.0.0"
}
```

`engine_ready` is `false` until the first transcription loads the model. That
is normal on a fresh start — the model loads lazily so the app boots fast.

---

## Error shape

Every error is a JSON object with a `detail` field:

```json
{ "detail": "File is too large. The limit is 25 MB." }
```

Validation errors (`422`) use FastAPI's standard array form:

```json
{
  "detail": [
    { "type": "value_error", "loc": ["body", "password"], "msg": "password must mix letters and numbers" }
  ]
}
```

---

## Status codes at a glance

| Code | When |
|---|---|
| `200` | Read succeeded |
| `201` | Account created |
| `202` | Upload accepted, job queued |
| `204` | Deleted |
| `401` | Missing or invalid token |
| `403` | Account disabled |
| `404` | Not found, or not yours |
| `409` | Conflict — duplicate email, job already running, not ready to export |
| `410` | Audio file no longer on disk |
| `413` | File too large |
| `422` | Validation failed |
| `429` | Rate limited |
