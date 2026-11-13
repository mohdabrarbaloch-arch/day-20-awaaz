# Awaaz — production image.
#
# ffmpeg is a hard dependency: faster-whisper shells out to it to decode
# anything that is not already 16 kHz mono PCM.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/awaaz/.cache/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user; the app never needs to write outside its own dirs.
RUN useradd --create-home --shell /bin/bash awaaz

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --upgrade pip && pip install .

COPY app ./app
COPY docs ./docs

RUN mkdir -p /app/uploads /home/awaaz/.cache \
    && chown -R awaaz:awaaz /app /home/awaaz

USER awaaz

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
