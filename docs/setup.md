# Setup

## Requirements

- Python 3.11 or newer
- **ffmpeg** on `PATH` — faster-whisper shells out to it to decode audio
- ~500 MB free disk for the model cache and uploads

### Installing ffmpeg

```bash
# Debian / Ubuntu
sudo apt-get install -y ffmpeg

# macOS
brew install ffmpeg

# Windows (with winget)
winget install Gyan.FFmpeg
```

Verify with `ffmpeg -version`.

---

## Local install

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-20-awaaz.git
cd day-20-awaaz

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

### Configure

```bash
cp .env.example .env
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> .env
```

Open `.env` and check two things:

- `SECRET_KEY` is the generated value, not the placeholder
- `DATABASE_URL` points where you want it (SQLite is fine to start)

### Run

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

The first transcription downloads the model. For `tiny` that is about 75 MB
and takes a few seconds on a decent connection. Subsequent runs use the cache.

---

## Docker

```bash
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
docker compose up --build
```

This starts PostgreSQL 16 and the app. Open <http://localhost:8000>.

The model cache and uploads are on named volumes, so a restart does not
re-download weights or lose files.

---

## Verifying the install

```bash
# Health — engine_ready is false until the first transcription loads the model
curl -s http://127.0.0.1:8000/api/health | python -m json.tool

# Tests
pytest

# Lint
ruff check .
ruff format --check .
```

---

## Troubleshooting

**`ffmpeg not found`**
faster-whisper needs the binary, not a Python package. Install it and confirm
`ffmpeg -version` works in the same shell you run the app from.

**First transcription is slow**
That is the model download. Watch the log — it prints `Loading whisper model=…`
and then `Model loaded in Ns`. After that, jobs are fast.

**`Refusing to start in production: SECRET_KEY is still the development default`**
Working as intended. Set a real `SECRET_KEY` and a non-SQLite `DATABASE_URL`,
or set `ENVIRONMENT=development`.

**Out of memory on a small VPS**
Drop to `WHISPER_MODEL=tiny` and `WHISPER_COMPUTE_TYPE=int8`. That combination
stays under ~200 MB resident.

**Uploads rejected with "does not look like audio"**
The file's first bytes are not a recognised container. This catches renamed
files. Re-export the audio properly rather than renaming it.
