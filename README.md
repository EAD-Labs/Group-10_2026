# Spoken Tutorial Dubbing

Dubs an English [Spoken Tutorial](https://spoken-tutorial.org) into an Indian language so the
dub stays in sync with the original video. **The only inputs are the English timed script and
the English video.**

For each tutorial and language you get two deliverables:

| | file | what it is |
|---|---|---|
| **Dubbed video** | `<lang>-dub.webm` | the original picture with the narration replaced by the dubbed voice |
| **Dubbed script** | `<lang>-script.docx` | the translation in the client's own format: a *Time \| Narration* Word table, on-screen terms in bold |

Supporting files come too: `<lang>.srt` subtitles, `<lang>-dub.wav` (the dubbed audio track
alone) and `<lang>-project.json` (every line's text, timing and measurements).

Languages: Tamil, Hindi, Marathi, Telugu, Kannada, Malayalam, Bengali, Gujarati, Punjabi and
Odia, with 37 Sarvam Bulbul v3 voices (male and female).

---

## How the pipeline works

```
English script (.docx/.odt) ─┐
                             ├─► 1 parse ─► 2 calibrate ─► 3 translate & fit ─► 4 voice ─► 5 align ─► 6 fine-tune ─► 7 mix & export
English video ───────────────┘                                                                                         │
                                                                         dubbed video + dubbed script + subtitles ◄────┘
```

1. **Parse.** The script's table is read row by row: the timestamp, the narration and the
   **bold** words. In Spoken Tutorials, bold marks something on screen: a menu, a button, a
   key. Each row's *time slot* is how long it has before the next row starts, minus a short
   pause so the dub doesn't sound rushed.
2. **Calibrate.** Each voice speaks at its own speed, which depends on the language, the
   speaker and the pace. The first time a combination is used, about 20 lines of *this*
   script are translated and voiced, and the voice's speed (syllables per second) is
   measured. The result is stored in `backend/out/voice-rates.json`, so this happens once
   per combination.
3. **Translate & fit.** **IndicTrans2** (an open model that runs locally) translates every
   line, with the bold on-screen terms protected so they stay in English, exactly as they
   appear on screen. Using the measured voice speed, each line's spoken length is predicted.
   If it won't fit its slot, **Sarvam-105b** (an LLM) condenses it while keeping every
   on-screen term. Lines that still don't fit are flagged for a person.
4. **Voice.** **Sarvam Bulbul v3** speaks each line at the chosen pace.
5. **Align.** A speech detector measures where the speech in each clip really starts and ends.
6. **Fine-tune.** Any clip that still runs past its slot is re-recorded up to 10% faster.
   Whatever still overruns is reported, not hidden.
7. **Mix & export.** The clips are placed at their timestamps on a track as long as the video,
   muxed onto the original picture, and the deliverables above are written.
   A QA report records, for every line, whether it lands in its slot and how much pause is
   left.

On the five LibreOffice Writer tutorials (716 lines, Tamil, pace 0.9), 714 lines land in
their slot, and every dubbed video is exactly as long as its original.
`backend/README.md` covers the measurements and the reasoning behind each stage.

---

## Repository layout

```
backend/            Python package - the pipeline and the HTTP API
  app/
    parsing/        reading .docx/.odt scripts, timings, bold terms
    duration/       speaking-rate model, syllable counting, voice calibration
    translate/      IndicTrans2, Sarvam/Groq condensing, term protection
    tts/            Sarvam Bulbul voices (+ a silent stub)
    align/          speech detection on each clip
    timeline/       placing clips, QA report
    export/         dubbed script (.docx), subtitles, mixdown (audio + video), manifest
    pipeline/       the runner that chains the stages, provider registry, track store
    api/            FastAPI endpoints, background jobs, tutorial library
    run.py          command-line entry point
  tests/            pytest suite
  README.md         technical deep dive
frontend/           the web UI (static HTML/CSS/JS, served by the API)
samples/            English scripts and videos to dub (videos are not in git)
docs/               project documents (HLD, client instructions, minutes)
```

---

## Setup

You need **Python 3.11**, about 2 GB of disk for the translation model, and a
**[Sarvam AI](https://dashboard.sarvam.ai) API key** (one key covers condensing and voice).
ffmpeg ships with the Python dependencies, so you don't need to install it separately.

```bash
# from the repository root
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux

pip install -r backend/requirements.txt

# Machine translation (IndicTrans2) - CPU build of torch keeps it small
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r backend/requirements-mt.txt
huggingface-cli login             # IndicTrans2 is gated: accept its licence on huggingface.co first

cp .env.example .env              # then set SARVAM_API_KEY=... in .env
```

`.env` is gitignored, so never commit your key. The model downloads from Hugging Face the
first time it is used.

Put the tutorials you want to dub in `samples/`; subfolders are fine. Each English script is
paired automatically with the English video whose file name matches its title, for example
`Table and table properties.docx` with `Tables-and-table-properties-in-Writer-English.webm`.

---

## Generating dubs

### 1. Web UI (easiest)

```bash
cd backend
uvicorn app.api.main:app --port 8000
```

Open **http://localhost:8000**, then:

1. Pick a tutorial (or upload a script and video).
2. Choose the language, speaker and pace.
3. Click **Dub video** and watch it run.

When it finishes you can play the dub, the original, or both side by side, and download the
dubbed video and the dubbed script. **Details** has every line for review: you can edit a
line and re-voice only that line. **History** has every previous dub.

A new 140-line tutorial takes about 5 minutes. Running the same tutorial, language, voice
and pace again is near-instant, because translations and clips are cached.

### 2. HTTP API (for scripts and other programs)

The same server exposes a JSON API.

```bash
# What can be dubbed, and with which voices / languages
curl http://localhost:8000/api/library
curl http://localhost:8000/api/voices
curl http://localhost:8000/api/languages

# Start a job from a tutorial in samples/ (paths as /api/library lists them) ...
curl -X POST http://localhost:8000/api/jobs \
  -F sample_script="more samples/Table and table properties.docx" \
  -F sample_video="more samples/Tables-and-table-properties-in-Writer-English.webm" \
  -F language=hi -F voice=shubh -F pace=0.9

# ... or upload your own files
curl -X POST http://localhost:8000/api/jobs \
  -F script=@my-tutorial.docx -F video=@my-tutorial.webm -F language=ta -F pace=0.9

# Poll until "status" is "done" (or "error")
curl http://localhost:8000/api/jobs/<job id>

# The result: "exports" holds a download URL for every deliverable
curl http://localhost:8000/api/jobs/<job id>/track
```

| endpoint | purpose |
|---|---|
| `GET /api/library` | tutorials found in `samples/`, each script paired with its video |
| `GET /api/voices`, `GET /api/languages` | choices for `voice` and `language` |
| `POST /api/jobs` | start a dub. Form fields: `sample_script`/`sample_video` **or** `script`/`video` uploads; `language` (`ta`, `hi`, `mr`, `te`, `kn`, `ml`, `bn`, `gu`, `pa`, `or`); `voice` (default `shubh`); `pace` (0.5-2.0, default 1.0) |
| `GET /api/jobs/{id}` | status, per-stage progress, live feed of finished lines |
| `GET /api/jobs/{id}/track` | every line (English, translation, timing, QA), the summary, and `exports` download URLs |
| `POST /api/jobs/{id}/segments/{line id}` | redo one line, optionally with your own text (`{"text": "..."}`) |
| `GET /api/jobs/{id}/files/{path}` | download a file from the job |
| `GET /api/health` | which keys and models are available |

Files are written to `backend/out/jobs/<job id>/<lang>/`.

### 3. Command line

```bash
cd backend
python -m app.run "../samples/more samples/Table and table properties.docx" \
    --video "../samples/more samples/Tables-and-table-properties-in-Writer-English.webm" \
    --language ta --pace 0.9 \
    --translator indictrans+sarvam --tts sarvam --aligner vad --workers 2 \
    --out out/my-dub
```

This writes `out/my-dub/ta/`, which contains `ta-dub.webm`, `ta-script.docx`, `ta.srt`,
`ta-dub.wav` and `ta-project.json`, and prints the QA summary.

Without any keys, `--translator echo --tts silent --aligner clip-bounds` runs the whole
pipeline with stand-ins, which is useful for checking an install.

---

## Tests

```bash
cd backend
python -m pytest
```

The suite runs offline, using stand-in providers.

## Good to know

- **Keep runs to one at a time on a laptop.** The translation model uses about 1 GB of
  memory while it runs.
- New lines need internet access and Sarvam credits. Cached results replay offline.
- Lines that couldn't be fitted, that overran, or that lost an on-screen term are marked
  **to review** in Details. Expect a handful per tutorial.
- The client's Tamil script and dub in `samples/` are used only to evaluate the pipeline,
  never as input.
