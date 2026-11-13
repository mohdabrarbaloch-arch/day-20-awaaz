# Usage

## The normal flow

1. **Create an account.** Email, password (8+ characters, letters and numbers),
   optional display name. You are signed in immediately.
2. **Drop a file.** Drag it onto the dropzone or click to browse. You get an
   inline player so you can confirm it is the right file before spending CPU.
3. **Pick a language, or don't.** Leaving it on "Detect automatically" is fine
   and costs a fraction of a second. Pinning it is slightly faster and avoids
   the occasional misdetection on short clips.
4. **Hit Transcribe.** The upload returns immediately and the job runs in the
   background. The list updates itself every 2.5 seconds.
5. **Open the transcript.** Click any row. You get every segment with its
   start time, plus export buttons.

---

## Export formats

| Format | Use it for |
|---|---|
| `.txt` | Pasting into a doc, word counts, feeding another tool |
| `.srt` | SubRip — YouTube, Premiere, DaVinci, most players |
| `.vtt` | WebVTT — HTML5 `<track>`, web players |
| `.md` | A readable transcript with `**MM:SS**` markers |

All four come from the same segment data, so they always agree.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/transcriptions/1/export?fmt=srt" \
  -o interview.srt
```

---

## Choosing a model

Set `WHISPER_MODEL` in `.env` and restart.

| Model | Size | CPU speed | Notes |
|---|---|---|---|
| `tiny` | 75 MB | ~2× real-time | Default. Good on clean speech. |
| `base` | 145 MB | ~1× real-time | Better with accents. |
| `small` | 480 MB | ~0.4× real-time | A clear step up in accuracy. |
| `medium` | 1.5 GB | slow | GPU recommended. |
| `large-v3` | 3 GB | GPU only | Best available. |

"2× real-time" means a 10-minute recording takes about 5 minutes.

For a GPU:

```env
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
WHISPER_MODEL=large-v3
```

---

## Verifying the real engine

The test suite uses a fake transcriber so it stays fast. To confirm the real
model works on your machine, transcribe something you know the words to:

```bash
python - <<'PY'
from app.engine import Transcriber

t = Transcriber(model_name="tiny")
result = t.transcribe("your-file.wav")

print("language:", result.language, result.language_probability)
print("duration:", result.duration_seconds, "s")
print("took:", result.processing_ms, "ms")
print()
for seg in result.segments:
    print(f"[{seg.start:6.2f} → {seg.end:6.2f}] {seg.text}")
PY
```

If the text matches what was said, the engine is working. If it is empty,
check that the file actually has speech in it — silence produces no segments
by design (VAD filters it out).

---

## Retrying a failed job

If a job fails (engine not loaded, corrupt file), the row shows `failed` with
the reason. `POST /api/transcriptions/{id}/retry` re-runs it from the stored
file — no re-upload needed. The UI does not expose this yet; use the API or
`/api/docs`.

---

## Housekeeping

Uploaded audio is kept so retry works. Deleting a transcript removes the row,
its segments and the audio file in one go.

To clear everything for a user, delete their transcripts through the API. To
nuke the whole install, stop the app and remove `uploads/` and the database
file.

---

## Limits worth knowing

- **25 MB per file** by default (`MAX_UPLOAD_MB`). That is roughly 25 minutes
  of 128 kbps MP3.
- **One job at a time** on a single CPU core. Concurrent uploads queue.
- **No speaker labels.** You get what was said and when, not who said it.
- **No live audio.** Files only.
