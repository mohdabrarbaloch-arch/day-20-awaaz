# Architecture — Awaaz

## The problem in one line

Transcription is a solved problem that is still annoying to use: every hosted
service wants a card, a per-minute fee, and your audio on their disk.

Awaaz is the same capability, self-hosted, with the audio never leaving the box.

---

## System diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser (vanilla JS, no build step)                                 │
│                                                                      │
│   index.html ── app.css ── app.js                                    │
│        │                                                             │
│        │  fetch + Bearer token                                       │
└────────┼─────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI application                                                 │
│                                                                      │
│  middleware:  CORS → security headers → slowapi rate limit           │
│                                                                      │
│  ┌────────────────┐   ┌──────────────────────────────────────────┐   │
│  │ /api/auth      │   │ /api/transcriptions                      │   │
│  │  register      │   │  POST   ""            → 202 + job        │   │
│  │  login         │   │  GET    ""            → paginated list   │   │
│  │  me            │   │  GET    /{id}         → detail+segments  │   │
│  └───────┬────────┘   │  GET    /{id}/export  → txt/srt/vtt/md   │   │
│          │            │  POST   /{id}/retry   → requeue          │   │
│          │            │  DELETE /{id}         → purge            │   │
│          │            └───────────┬──────────────────────────────┘   │
│          │                        │                                  │
│          │  security.py           │  uploads.py                      │
│          │  bcrypt + JWT          │  magic bytes, safe paths         │
│          │                        │                                  │
│          │                        ▼                                  │
│          │            ┌───────────────────────────┐                  │
│          │            │ BackgroundTasks           │                  │
│          │            │  _run_transcription(id)   │                  │
│          │            │  own DB session           │                  │
│          │            └───────────┬───────────────┘                  │
│          │                        │                                  │
│          │                        ▼                                  │
│          │            ┌───────────────────────────┐                  │
│          │            │ engine.py                 │                  │
│          │            │  Transcriber (lazy,       │                  │
│          │            │  thread-safe singleton)   │                  │
│          │            │  → faster-whisper         │                  │
│          │            │  → CTranslate2 int8       │                  │
│          │            └───────────┬───────────────┘                  │
│          │                        │                                  │
└──────────┼────────────────────────┼──────────────────────────────────┘
           │                        │
           ▼                        ▼
   ┌───────────────┐        ┌──────────────────┐
   │  Database     │        │  Disk            │
   │  SQLite /     │        │  uploads/u{id}/  │
   │  PostgreSQL   │        │  {uuid}.wav      │
   │               │        │                  │
   │  users        │        │  model cache     │
   │  transcriptions│       │  (~75 MB tiny)   │
   │  segments     │        └──────────────────┘
   └───────────────┘
```

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Web framework | FastAPI 0.115 | Async, typed, OpenAPI for free |
| ASR | faster-whisper 1.2 (CTranslate2) | 4× faster than openai-whisper at the same accuracy |
| Audio decode | ffmpeg | Handles every container without Python bindings |
| ORM | SQLAlchemy 2.0 (typed `Mapped[]`) | Real types, real migrations path |
| Validation | Pydantic v2 | Request/response contracts |
| Auth | python-jose (HS256) + passlib/bcrypt | Boring and correct |
| Rate limit | slowapi | Per-IP, decorator-based |
| Frontend | Vanilla JS + CSS | No build step, no dependency drift |
| DB | SQLite dev / PostgreSQL 16 prod | Zero-config locally, real in prod |

---

## Data flow: one upload

1. **Client** posts `multipart/form-data` with `file` and an optional
   `?language=` hint, plus `Authorization: Bearer <jwt>`.
2. **Auth dependency** decodes the JWT, loads the user, rejects inactive
   accounts with `401`.
3. **Validation** (`uploads.py`):
   - size cap checked against `Content-Length` *and* enforced again while
     streaming, so a lying header cannot fill the disk;
   - MIME type checked against the allow-list;
   - first 64 bytes sniffed for a real container signature — a `.mp3` that is
     actually a zip is refused with `422`;
   - extension/container agreement checked when both are specific.
4. **Storage**: the file is written to `uploads/u{user_id}/{uuid}{ext}`. The
   original filename is kept in the database for display only and is never
   used as a path.
5. **Row created** with `status=queued`, response is `202 Accepted` with the
   record. The client gets an ID immediately.
6. **Background task** `_run_transcription(id)` opens its *own* session (the
   request's session is already closed), flips the row to `processing`, and
   calls the engine.
7. **Engine** loads the model on first use (cached for the process), runs
   `transcribe()` with VAD enabled, and returns segments plus language and
   duration.
8. **Persistence**: text, language, duration, model name and processing time
   go on the transcription row; each segment becomes a `segments` row with
   start, end, text and confidence.
9. **Client polls** `GET /api/transcriptions` every 2.5 s while anything is
   `queued` or `processing`, and stops when nothing is active.

---

## Why the engine is a separate module

`engine.py` is the only file that imports `faster_whisper`. Everything else —
subtitle rendering, validation, persistence — is pure and testable without
downloading 75 MB of weights.

That split is why the suite runs in two seconds: `conftest.py` swaps in a
`FakeTranscriber` that returns deterministic segments, and the real model is
never touched. The real engine is verified separately, by hand, on real audio.

---

## Timestamp handling

Subtitle timing is the one place where a small bug is very visible, so it
lives in exactly one function:

```python
format_timestamp(3661.25)  # "01:01:01,250"
format_timestamp(25 * 3600)  # "25:00:00,000"  — hours do not wrap at 24
format_timestamp(-5)  # "00:00:00,000"  — clamped
format_timestamp(nan)  # "00:00:00,000"
```

`merge_short_cues` fixes the other common problem: Whisper sometimes emits a
0.2-second cue for a whole sentence, which flashes past unreadably. Short cues
are stretched to a minimum duration, but never past the next cue's start.

---

## Security model

| Threat | Mitigation |
|---|---|
| Password theft from DB | bcrypt, 12 rounds, per-hash salt |
| Password truncation surprise | hard reject over 72 bytes instead of silent cut |
| Token forgery | HS256 with a 32+ char secret, verified per request |
| Account enumeration | identical `401` message and work for unknown email |
| Cross-user data access | ownership filter in the query; `404` not `403` |
| Path traversal | basename only, ASCII-only, UUID on disk, resolved-path check |
| Malicious upload | magic-byte sniffing, MIME allow-list, streaming size cap |
| Brute force | slowapi per-IP limits on auth and transcription |
| XSS | CSP with no `unsafe-inline` for scripts; all DOM writes via `textContent` |
| Clickjacking | `X-Frame-Options: DENY` + `frame-ancestors 'none'` |
| Production misconfiguration | app refuses to boot with dev defaults |

---

## Scaling notes

**Where it breaks first: the model.** One `tiny` model on one CPU core handles
roughly one job at a time. Two concurrent uploads queue behind each other.

The path out, in order of effort:

1. **Bigger box.** `base` or `small` on a 4-core VPS is a one-line change and
   covers most personal use.
2. **GPU.** `WHISPER_DEVICE=cuda`, `WHISPER_COMPUTE_TYPE=float16`. Roughly
   20–40× faster; a `large-v3` becomes practical.
3. **Real queue.** `BackgroundTasks` dies with the process. Move to Celery or
   RQ with Redis so a restart does not lose queued jobs, and so workers can
   scale independently of the web tier.
4. **Shared rate limiting.** slowapi's in-memory store is per-process. Behind
   N workers the effective limit is N×. Point it at Redis.
5. **Object storage.** Local disk does not survive a container reschedule.
   S3 or R2, with the DB holding the key.
6. **Migrations.** `create_all()` is fine for one deploy. Alembic before the
   second.

**What scales cleanly already:** the web tier is stateless apart from the
model cache, so it can be replicated behind a load balancer as soon as the
queue and rate limiter are shared.

---

## Deliberate non-goals

- **No speaker diarization.** It needs a second model and a clustering pass;
  out of scope for a single-day build.
- **No live streaming.** Files only. Streaming needs a different decode path
  and a WebSocket protocol.
- **No cloud fallback.** The whole point is that it runs locally. If you want
  a hosted API, use one.
