# Spoken Tutorial dubbing - backend

*Setup, running and the API are in the [main README](../README.md). This file is the
technical deep dive: what each stage does, and the measurements behind it.*

Takes an English Spoken Tutorial timed script (and optionally its video) to a
dubbed track in Tamil - or Hindi, Marathi, Telugu, Kannada, Malayalam,
Bengali, Gujarati, Punjabi or Odia - that fits the original video's timing. **The English script
and video are the only inputs.** The client's human Tamil dub and script are
used only as an evaluation baseline (tests, report comparisons, the optional
`review.py --reference`), never by the pipeline itself:

```
parse -> translate (IndicTrans2 draft, Sarvam LLM shortens) -> synthesise (Sarvam)
      -> fit audio pace -> align (VAD) -> timeline -> QA
      -> export (dubbed script .docx, SRT, dub audio, dubbed video)
```

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate      # from the repository root
pip install -r backend/requirements.txt

# Local machine translation (optional, ~1 GB with CPU torch):
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r backend/requirements-mt.txt
huggingface-cli login     # IndicTrans2 is gated: accept its licence on huggingface.co first

cp .env.example .env      # then fill in SARVAM_API_KEY (one key: shortening and voice)
```

### The review UI

```bash
cd backend
uvicorn app.api.main:app --reload
# open http://localhost:8000
```

The main screen is only the dubbing itself:

1. **Pick a tutorial.** Every English script under `samples/` (subfolders
   included, `.docx` or `.odt`) is paired with its English video by title
   (`app/api/library.py`) and shown as a card with a poster frame. The client's
   Tamil script and dub are not offered - they are evaluation material. Or
   upload a script and video.
2. **Language, speaker, pace.** Ten languages; 37 Bulbul v3 voices (Sarvam's
   recommended ones first, each marked male or female); pace 0.7-1.0. The
   language hint says whether this voice has been measured at this pace - if
   not, the run measures it first (see *Calibrating automatically*).
3. **Watch it run.** A stepper (measure voice, translate & fit, voice, align,
   fine-tune, mix) and a live feed of lines as they are translated - kept or
   condensed - and then voiced, each playable.
4. **The result.** The dub with subtitles, switchable to the **original**
   at the same moment, or **side by side** in sync with either soundtrack;
   four headline numbers; download.

One click away: **Details** (every line - English, machine draft, final text,
slot, measured speech, drift - editable and re-voiceable one at a time, HLD
UC-03; the quality numbers explained; the settings and models used; the
files), **History** (every previous dub), **System** (keys and models present;
keys never reach the page). Translator, aligner and parallelism sit under
*Advanced*; with no keys the stub providers still run end to end.

### The command line

```bash
cd backend
# real chain
python -m app.run ../samples/Timed-script-sample-english.docx --language ta \
    --translator indictrans+sarvam --tts sarvam --aligner vad \
    --video ../samples/Overview-of-Synfig-English.webm --workers 4

# stubs only - no keys, no downloads
python -m app.run ../samples/Timed-script-sample-english.docx --language ta --duration 663.2

python -m app.cli ../samples/Timed-script-sample-english.docx --language en --duration 663.2
python -m app.calibrate_voice --script ../samples/Timed-script-sample-english.docx --paces 1.0 0.9 0.8 0.7
python -m pytest tests
```

### Providers

Every stage sits behind a Protocol (`app/pipeline/interfaces.py`) and is chosen
by name from `app/pipeline/registry.py`, so switching provider is
configuration (HLD UC-07). Stubs stay registered beside the real ones and
declare `is_stub = True`; every run names the stubs still in the chain.

| stage | real | stub |
|---|---|---|
| translate | `indictrans+sarvam` - IndicTrans2 drafts locally, sarvam-105b edits overruns; `sarvam` - LLM only; `indictrans+groq` / `groq` - the same on GPT-OSS 120B | `echo` |
| synthesise | `sarvam` - Bulbul v3, with pace correction | `silent` |
| align | `vad` - Step 1's speech detector | `clip-bounds` |
| export | `script` (the dubbed script as a Time \| Narration .docx), `srt`, `mixdown` (dub WAV + remuxed video) | `manifest` (stand-in for OTIO / Kdenlive) |

Layout: `app/parsing` (script reader, cues, checklist rules), `app/duration`
(rate model, syllable counter, audio measurement), `app/translate`,
`app/tts`, `app/align`, `app/timeline` (placement, QA), `app/export`,
`app/pipeline` (runner, registry, track store), `app/api` (FastAPI endpoints,
background jobs, tutorial library; the page itself is `../frontend/`),
`app/config.py` (settings and secrets), `app/http.py` (shared retrying POST).

## What it does that a naive parser does not

A timed script has two kinds of row. **Narration rows** carry a `MM:SS`
timestamp. **Cue rows** carry no timestamp and begin with `@MM:SS` - they tell
the editor to splice audio from another tutorial into the base video.

A narration row's window runs to the next narration row, but if a cue fires
inside that window the embedded clip is already using it. On the Synfig sample
that is **90 s of the 663 s video**, and a row sitting in front of a clip looks
like it has a 13 s budget when it really has 3 s. Writing narration - or a hold -
into that space would land it on top of the embedded audio.

So each segment reports three numbers:

| field | meaning |
|---|---|
| `raw_budget` | the whole window to the next narration row |
| `cue_reserved` | seconds inside it taken by embedded clip audio |
| `narration_budget` | what narration may actually occupy - **use this one** |
| `trailing_slack` | free time after the clip; genuinely available for holds |

The second thing: the checklist's 60/80-character limits (2.3.1, 2.3.2) apply to
**sentences**, but a script row is an *activity* that often holds several. On the
English sample, 21 rows exceed 80 characters while only 12 sentences actually
break the rule. Budgets attach to rows; validation runs over sentences.

## The duration model

`app/duration` predicts spoken length in **syllables**, not characters. Tamil is
an abugida - one akshara carries a consonant-vowel unit that Latin script spells
with three or four characters - so character counts are not comparable across
languages. Aksharas are counted for Tamil and Devanagari, vowel groups for
Latin, and every counter is mixed-script because these scripts embed English
technical terms freely.

Calibrated on the client's Synfig pair (same 663.2 s video, English and Tamil):

| | English | Tamil |
|---|---|---|
| delivered pace (median) | 3.00 syl/s | **4.00 syl/s** |
| text needed at 3.00 syl/s | 536 s | **770 s** |
| narration budget available | 561 s | 561 s |
| segments over budget | 42 / 95 | **83 / 95** |

The Tamil track needs **37% more time than exists**, so it was delivered a third
faster than the English. That gap is what the fitting engine has to close in the
text rather than in the speaking rate.

`DEFAULT_RATES` deliberately targets every language at the English reference
pace: the project's whole premise is that the text absorbs the expansion.

## Step 1 - measuring the real audio

The model above predicts from the script alone. `app/media` and
`app/duration/measure.py` check it against the recordings the client supplied.

Voice-activity detection, not forced alignment: Step 0 already tells us where
each segment's window is, so what is missing is only *where inside that window
the speech stops*. Energy VAD needs no model download and behaves the same on
Tamil as on English. Word-level alignment is a separate job, needed later to
measure drift on generated audio.

```bash
python -m app.calibrate --script ../samples/Timed-script-sample-english.docx                         --video  ../samples/Overview-of-Synfig-English.webm --language en
```

Measured on the Synfig pair, embedded-clip windows excluded:

| | English | Tamil |
|---|---|---|
| articulation rate (aggregate) | 3.91 syl/s | **4.85 syl/s** |
| median trailing pause | 0.41 s | **0.00 s** |
| segments with no pause at all | 25 / 84 | **50 / 84** |
| share of window actually spoken | 73.2% | 84.4% |

Two separate things were done to make Tamil fit: it is spoken **24% faster**,
*and* **59 seconds of pause were deleted**. Neither is visible in the script -
both are audible.

This changed the model in two ways. The reference rate became an articulation
rate (3.91, measured on speech) rather than a syllables-per-window figure
(3.00, which silently averaged in the pauses). And `PAUSE_RESERVE` now withholds
0.40 s per segment before the translator sees the budget - fixed rather than
proportional, because trailing pause correlates with window length at r = 0.06.

The payoff is fewer false alarms. Scored against the English script - which was
recorded and delivered at exactly these timings, so anything flagged is a model
error - the Step 0 model called 42 of 95 segments over budget. The Step 1 model
calls 11.

It also revised the headline gap downwards: Tamil needs **13% more speaking
time than exists**, not the 37% the script-only model implied. Rephrasing can
close 13%.

## The pipeline

`app/pipeline/runner.py` owns the order and the plumbing, not the intelligence.
Translation and synthesis - the metered stages - run concurrently with
`--workers N` / `max_workers`. Every run persists its full state to
`out/<lang>/track.json` (`app/pipeline/store.py`), which is what lets a later
request regenerate one segment without re-running the rest.

### The budget the pipeline actually targets

Step 2 was first written against the Step 0 model and has been rebased onto
Step 1's. The translator is handed `RateModel.speaking_budget(segment)`, which
is narrower than the segment's window twice over - an action cue means an
embedded clip already owns part of it, and the tail belongs to the pause the
narrator has to leave. Targeting the raw window yields a track where every line
fits and none of them breathe, which is the delivery the client complained
about.

The QA report therefore carries `pause_after` beside `drift`, and a segment is
`unrushed` only if it fits *and* leaves an audible gap. Scored against the
client's own delivered Tamil text:

| | English | Tamil |
|---|---|---|
| segments over budget | 11 / 95 | **63 / 95** |
| median pause left | 1.16 s | **0.00 s** |

Predicted from the text alone, that reproduces what Step 1 measured in the
audio - a 0.00 s median pause, most segments with no gap at all. Two
independent routes to the same answer.

Alignment uses the same detector Step 1 measured the client's recordings with
(`app/media/vad.py`), so a generated track and the client's baseline are
compared on equal terms rather than by two implementations that could disagree.

## Module 2 - duration-constrained translation

Two models, each doing the part it is good at:

```
IndicTrans2 (local, free) -> draft
          |
   measure it OURSELVES  -- fits, on-screen terms intact --> keep it (no LLM call)
          |
     over budget, or a menu name got translated
          |
sarvam-105b: "edit this draft; it uses 22 aksharas, the limit is 14"
          |
   measure again -> fits -> keep  |  3 rounds, still over -> escalate to the author
```

The shortener is Sarvam's `sarvam-105b` (`SarvamChat` in `app/translate/llm.py`,
chat completions v1), so a single `SARVAM_API_KEY` pays for both shortening and
speech. GPT-OSS 120B on Groq is kept behind the same `ChatModel` interface as
`--translator indictrans+groq`.

IndicTrans2 (`app/translate/indictrans.py`, the distilled 200M English->Indic
checkpoint) runs on CPU and translates the whole track in batches before the
per-segment loop starts. Drafts are cached in `out/translation-cache.json` like
every LLM answer. The LLM only ever sees segments the draft could not carry,
which on the client's script is about 60% of segments rather than all of them.

On-screen terms - the script's bold text: menu names, buttons, keys - must
stay in Latin script exactly as written, because the learner matches them
against the screen. Unprotected, IndicTrans2 renders "Synfig" as "of
synchronisation" and transliterates shell commands. So `app/translate/terms.py`
swaps them for `TERMX1`-style placeholders before translation and restores
them after; IndicTrans2 carries the placeholders through and attaches Tamil
case endings to them naturally. A segment's own bold terms are protected as
often as they were bolded (S-021 bolds the key "Enter", not the verb that opens
the next sentence); a term bold only elsewhere is protected only if it is a
name rather than a word whose lower-case form the script also uses ("Synfig"
yes, "Next" no). Commands, URLs, file names and versions are always protected.
A draft that still lost a term goes to the LLM to have it restored.

`--translator sarvam` is the LLM-only path (the model translates from
scratch inside the same loop), kept for comparison.

Three things decide whether the loop works, on either path.

**The budget is the speaking budget.** `RateModel.speaking_budget` - the window
less the reserved pause - not the window. Targeting the window buys back about
two aksharas per segment and produces a track where every line fits and none of
them breathe.

**The model is never trusted to count.** Language models are poor at counting
syllables and will assert that an over-long line fits. Every candidate is
measured with `count_syllables`, the same counter that calibrated the duration
model against the client's recordings, and only that measurement decides.

**The budget is expressed in aksharas, not seconds.** The model has no idea
what speaking rate we assume, so seconds are a target it cannot evaluate. Each
request carries the akshara budget and an approximate word count derived from
the 2.75 aksharas-per-word measured in the client's Tamil script.

Prompts encode the client's own rules (`app/translate/prompts.py`): on-screen
terms kept in Latin script exactly as written, everyday computing words
allowed in Tamil script, simple
vocabulary, one instruction per sentence, two sentences may merge.

### What the job actually requires

Measured against the client's Tamil, per segment, to hit a comfortable pace:

| cut needed | meaning | segments |
|---|---|---|
| 0-10% | tighten a phrase | 15 |
| 10-25% | real rewriting | 19 |
| 25-40% | drop a clause | 22 |
| **40%+** | **meaning has to go** | **11** |

Median cut: **24%**. So the loop can be expected to fit most segments and to
escalate a stubborn tail. Those escalations are the point, not a failure: a
line needing to lose half its content needs a person to decide what goes, and
the CLI prints them worst-first with the source, the best attempt and the
shortfall; the UI's "Needs an author" filter lists them for editing.

Translations are cached on disk (`out/translation-cache.json`), keyed on source,
language, budget and model - so correcting one segment does not re-pay for the
other ninety-four, and a changed budget correctly misses rather than returning
text fitted to the old one.

## Speech - Sarvam Bulbul, and closing the loop on duration

`app/tts/sarvam.py` calls `POST https://api.sarvam.ai/text-to-speech` (key in
`SARVAM_API_KEY`, model `bulbul:v3` and voice `shubh` by default - v2 is
deprecated; `SARVAM_TTS_MODEL` / `SARVAM_SPEAKER` override). The clip's
duration is measured from the decoded audio, never assumed, and clips are
cached in `out/tts-cache/` by text, voice, pace and model.

Two steps make "fits on paper" agree with "fits in the audio":

1. **Calibrate the voice, at the chosen pace.** The default rates were measured
   on the English narrator; a synthetic voice has its own pace, and a different
   one at every `pace` setting. `python -m app.calibrate_voice --paces 1.0 0.9
   0.8 0.7` translates long lines of the ENGLISH script with our own IndicTrans2
   drafter, synthesises them at each pace, measures the speech with the Step 1
   detector, and saves each rate to `out/voice-rates.json`. A run at
   `--pace 0.8` then budgets text at what the voice does at 0.8.
2. **Correct the pace.** After synthesis, any clip whose measured speech
   overruns its budget by more than 250 ms is requested again at the pace
   that would fit, capped at +10% of the track's base pace (HLD S14's rate
   tolerance). What still
   overruns is flagged on the segment: the text has to get shorter.

### Calibrating automatically

A voice speaks every language, at every pace, at its own rate. The first job
that needs a voice/language/pace combination with no rate in
`out/voice-rates.json` runs a `calibrate` stage before translating: 20
length-stratified lines of **that job's own English script**, drafted by
IndicTrans2 (drafts the translate stage needs anyway), voiced and measured.
About 20 TTS calls, once per combination (`app/duration/calibrate.py`). So a
new language, a female voice or a new pace is budgeted correctly with no
manual step and no human translation involved.

### What the voice is slow on: English terms and numbers

Calibrated voices count speech in `spoken_units` (`app/duration/syllables.py`),
not plain aksharas. Fitting clip span against (aksharas, Latin syllables,
digits) over all 716 clips of the five LibreOffice tutorials gave 0.168 s per
akshara, 0.234 s per Latin syllable and 0.443 s per digit: Bulbul slows down
for on-screen English ("Bullets and Numbering") and reads numerals in full,
which plain counting scored as nothing. Latin syllables therefore weigh 1.4
aksharas and digits 2.6. The residual error per line fell from 0.71 s to
0.55 s. The human-narrator model and the Step 1 analysis keep plain counts.

### Choosing the pace

Bulbul v3 speaks Tamil at about 6.1 aksharas/s at its natural pace (1.0) -
denser than the human dub the client found rushed. `--pace` (and the UI's pace
field) slows the whole track; the cost is time per line, so more lines are
shortened to fit. Which pace sounds right is the client's call, made by ear on
full-length dubs at each setting.

## Mixdown - something to watch

`--export mixdown` places every clip at its timeline start (lead-in trimmed)
on a track the length of the base video, carries the base video's own audio
through the embedded-clip windows, and writes `<lang>-dub.wav`. Given
`--video`, it also remuxes the picture with the dub into `<lang>-dub.webm`
(or `.mp4`), copying the video stream untouched.

## Known limitations

- Numerals and English terms are weighted by a fit on Tamil (716 clips). The
  one Hindi run measured English terms at 1.64x an akshara against Tamil's
  1.45x; the shared 1.4 holds until more Hindi is fitted. Spelling acronyms
  letter by letter ("MHRD") was tried and did not improve the fit.
- Bold words in the script are kept in English as on-screen terms, including
  ordinary words the author bolded ("table", "cursor"). Whether the client
  wants those translated is a style decision to confirm.
- Holds are not inserted at non-action gaps yet (`hold_after` is always 0).
- Drift is measured per clip against its budget, not word-by-word against the
  video; that needs forced alignment (WhisperX / MFA).
- Embedded clips carry the base video's (English) audio; a Tamil release needs
  the Tamil editions of those source tutorials.
- Only the `Time | Narration` timed-script format is handled, in Word
  (.docx) or OpenDocument (.odt) files - detected by content, since some
  client scripts are .odt files named .docx.
- The UI is a single-user demo: jobs live in memory and in `out/jobs/`.

---

## Reading the base video

`app/media/probe.py` reads a WebM/Matroska duration straight from the
container - no ffmpeg, a few dozen lines of stdlib. Pass `--video` to any CLI
instead of `--duration` and the number under every budget comes from the file
rather than from someone's memory.

What that established on the client's Synfig pair:

| | |
|---|---|
| English video | **663.198 s** |
| Tamil video | **663.268 s** |
| the `663.2` used everywhere before | correct, to the tenth |
| the two tracks | 70 ms apart - one base video, reused, exactly as the client describes |
| the 11 action cues | all anchored inside the video |

The videos are gitignored (large, and not ours to redistribute); put them in
`samples/` beside the scripts. `tests/test_media.py` skips rather than fails when they are absent.

### Validating a track by eye

The strongest check available on the pipeline needs no toolchain at all:

```bash
python -m app.run ../samples/Timed-script-sample-english.docx --language en \
    --video ../samples/Overview-of-Synfig-English.webm --out ../out
```

Open the .webm in VLC and drop `out/en/en.srt` onto it. Each subtitle should
appear as the narrator says those words. If they track the narration, then
segment boundaries, timestamps and timeline placement are all correct - parse,
timeline and export validated in one pass. Subtitles drifting steadily later
would mean a segment-indexing bug; a subtitle sitting over an embedded clip
would mean cue rows are being read as narration.

Two caveats worth stating at a demo: the audio is silence and the aligner
reads clip bounds, so the drift figure measures the script against itself, not
narration against video. That number becomes real when forced alignment lands.
