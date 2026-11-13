# Awaaz آواز

**Speech to text that runs on your own machine.**

Upload an audio file, get a transcript with timestamps, export it as SRT, VTT, Markdown or plain text. No API keys, no per-minute billing, no audio leaving your server.

![Python](https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)
![Tests](https://img.shields.io/badge/tests-107%20passing-4ade80?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)

---

## Why this exists

Every transcription service wants a credit card and a per-minute fee, and every one of them wants your audio uploaded to their servers. For a podcast, a lecture recording, a client call or a doctor's dictation, that's a bad trade.

Awaaz runs [faster-whisper](https://github.com/SYSTRAN/faster-whisper) locally. The `tiny` model is about 75 MB and transcribes roughly twice real-time on a single CPU core. Your audio stays on the disk you control.

---

## What it does

- **Real speech recognition** — faster-whisper (CTranslate2), not a stub. Verified end-to-end on real audio.
- **Timed segments** — every line carries a start and end, so subtitles line up.
- **Four export formats** — `.txt`, `.srt`, `.vtt`, `.md`, all generated from the same segment data.
- **Language detection or override** — let the model guess, or pin it to `en`, `ur`, `hi`, `ar` and nine more.
- **Background jobs** — upload returns `202` immediately; the UI polls and fills itself in.
- **Per-user isolation** — you only ever see your own transcripts. Someone else's ID returns `404`, not `403`, so a request can't even confirm the record exists.
- **Retry without re-uploading** — a failed job can be re-run from the stored file.
- **Mobile-first UI** — no framework, no build step, three static files.

---

## Screenshots

| Sign in | Upload | Transcript |
|---|---|---|
| `docs/screenshots/auth.png` | `docs/screenshots/upload.png` | `docs/screenshots/transcript.png` |

---

## Quick start

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-20-awaaz.git
cd day-20-awaaz

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> .env

uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>, create an account, drop a file in.

The first transcription downloads the model weights (~75 MB for `tiny`) and takes a few seconds longer than the rest.

### With Docker

```bash
docker compose up --build
```

That brings up the app plus PostgreSQL 16. Open <http://localhost:8000>.

---

## Choosing a model

Set `WHISPER_MODEL` in `.env`:

| Model | Size | Speed (CPU) | When |
|---|---|---|---|
| `tiny` | ~75 MB | ~2× real-time | Default. Fine for clear speech. |
| `base` | ~145 MB | ~1× real-time | Better on accents and noise. |
| `small` | ~480 MB | ~0.4× real-time | Noticeably more accurate. |
| `medium` | ~1.5 GB | slow on CPU | Use a GPU. |
| `large-v3` | ~3 GB | GPU only | Best accuracy. |

For a GPU, set `WHISPER_DEVICE=cuda` and `WHISPER_COMPUTE_TYPE=float16`.

---

## API

All transcription routes need `Authorization: Bearer <token>`.

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/auth/register` | Create an account, returns a token |
| `POST` | `/api/auth/login` | Exchange credentials for a token |
| `GET` | `/api/auth/me` | Current user |
| `POST` | `/api/transcriptions` | Upload audio (`multipart/form-data`, field `file`) → `202` |
| `GET` | `/api/transcriptions` | Paginated history (`limit`, `offset`) |
| `GET` | `/api/transcriptions/{id}` | Full record with segments |
| `GET` | `/api/transcriptions/{id}/export?fmt=srt` | Download (`txt`/`srt`/`vtt`/`md`) |
| `POST` | `/api/transcriptions/{id}/retry` | Re-run a failed job |
| `DELETE` | `/api/transcriptions/{id}` | Delete record, segments and audio |
| `GET` | `/api/health` | Liveness + whether the model is loaded |

Interactive docs at `/api/docs`.

```bash
# Upload
curl -X POST http://127.0.0.1:8000/api/transcriptions \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@interview.mp3"

# Export as subtitles
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/transcriptions/1/export?fmt=srt" -o interview.srt
```

---

## Configuration

Everything lives in `.env` — see `.env.example` for the full list with comments. The ones that matter:

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | dev placeholder | **Must** be changed. App refuses to start in production with the default. |
| `DATABASE_URL` | `sqlite:///./awaaz.db` | Point at PostgreSQL in production. |
| `WHISPER_MODEL` | `tiny` | See the table above. |
| `MAX_UPLOAD_MB` | `25` | Enforced while streaming, not just from `Content-Length`. |
| `RATE_LIMIT` | `30/minute` | Per IP. |

---

## Security

- bcrypt (12 rounds) for passwords, with a hard 72-byte cap rather than silent truncation.
- JWT (HS256), 24-hour expiry, verified on every request.
- Uploads validated by magic bytes, not extension — a `.mp3` that's really a zip is refused.
- Stored filenames are UUIDs; the original name is never used on disk.
- Streaming size cap, so a lying `Content-Length` can't fill the volume.
- CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, HSTS in production.
- Rate limiting on auth and transcription routes.
- Ownership checks return `404` rather than `403`.

---

## Tests

```bash
pytest          # 107 tests
ruff check .    # clean
ruff format --check .
```

The suite uses an in-memory database and a fake transcriber, so it runs in about two seconds and never downloads weights. The real engine is exercised separately — see `docs/usage.md`.

---

## Project layout

```
app/
  config.py        settings, production guards
  db.py            engine, session, SQLite FK pragma
  models.py        User, Transcription, Segment
  schemas.py       Pydantic request/response models
  security.py      bcrypt, JWT, auth dependency
  engine.py        faster-whisper wrapper (lazy, thread-safe)
  subtitles.py     timestamp maths, SRT/VTT/MD/TXT renderers
  uploads.py       magic-byte validation, safe paths
  routers/
    auth.py
    transcriptions.py
  static/          index.html, app.css, app.js
tests/             107 tests
docs/              setup, usage, API reference
```

---

## Known limits

- **CPU-only by default.** `tiny` is fast but not perfect on heavy accents or background noise. Bump the model or add a GPU.
- **No speaker diarization.** You get "who said what" only if you can tell from the words.
- **No live streaming.** Files only — upload, then transcribe.
- **`create_all()` instead of migrations.** Fine for one deploy; add Alembic before you have real users.
- **Rate limiter is per-process.** Behind multiple workers it multiplies; use Redis before scaling out.

---

## License

MIT — see [LICENSE](LICENSE).

Built as Day 20 of a 30-day build challenge.
