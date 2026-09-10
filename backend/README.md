# Spoken Tutorial Generator - backend

Turns a Spoken Tutorial timed script into segments, action cues and per-segment
time budgets, validated against the Dubbers' Checklist.

## Run it

```bash
cd backend
python -m app.cli "../Timed-script-sample-english.docx" --language en --duration 663.2
python -m app.cli "../Tamil-script-sample.docx" --language ta --duration 663.2
python tests/test_parser.py        # or: pytest tests
python tests/test_pipeline.py
python tests/test_media.py         # skips if the client videos are absent
python tests/test_api.py
```

## HTTP API (for `../frontend`)

`app/api.py` is a thin FastAPI wrapper - no new pipeline logic, just
`parse_script`/`run_track`/`run_segments` reached over HTTP for the frontend.
State (parsed scripts, generated tracks) lives in memory for the life of the
process; there is no database yet.

```bash
uvicorn app.api:app --reload --port 8123
```

- `POST /api/scripts` - multipart upload (`script`, `language`, optional
  `video` or `duration`) -> `{id, script}`
- `GET /api/scripts/{id}` -> the stored `ParsedScript`
- `POST /api/scripts/{id}/run` - `{language, source_language?, translator?,
  tts?, aligner?, exporters?}` -> `{track, stubbed_stages}`
- `POST /api/scripts/{id}/run-segments` - `{language, segment_ids}` -> updated
  track (HLD UC-03: regenerate one segment without a full re-render)

`--duration` is the length of the base video. It sets the last segment's budget;
without it the parser assumes the script's median window. Better, pass the video
itself and let the duration be read from the container:

```bash
python -m app.cli "../Timed-script-sample-english.docx" --language en \n    --video ../Overview-of-Synfig-English.webm
```

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
python -m app.calibrate --script ../Timed-script-sample-english.docx                         --video  ../Overview-of-Synfig-English.webm --language en
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

## Step 2 - the pipeline, end to end

```bash
python -m app.run ../Tamil-script-sample.docx --language ta --duration 663.2
```

`parse -> translate -> synthesise -> align -> timeline -> QA -> export`, running
today with the hard stages stubbed. Every stage sits behind a Protocol in
`app/pipeline/interfaces.py` and is chosen by name from `app/pipeline/registry.py`,
so replacing a stub is a config change (HLD UC-07), and `run_segments` re-runs a
single segment without a full re-render (UC-03).

| stage | today | replaced by |
|---|---|---|
| translate | `echo` (stub, passes text through) | Module 2 + an LLM |
| synthesise | `silent` (stub, silence of predicted length) | Piper, then Sarvam |
| align | `clip-bounds` (stub) / **`vad` (real)** | word-level WhisperX / MFA |
| export | **`srt` (real)**, `manifest` (stand-in) | OpenTimelineIO / Kdenlive XML |

Every run prints which stages were stubbed, so no demo can mistake a stub's
arithmetic for real audio.

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

## Known limitations

- Bare numerals (`16.04`, `0`) are not counted as syllables - how they are
  spoken is language-specific. Needs a spoken-form expansion once the client
  confirms the convention.
- Rates are calibrated from one script pair. Recalibrate as more arrive.
- Numerals are the largest remaining error source: "Synfig version 1.0.2" counts
  as 4 syllables but takes 3.4 s to say. Needs spoken-form expansion per language.
- Prediction error is MAE 0.63 s (down from 1.11 s), still short of the 250 ms
  drift criterion - which is measured post-synthesis by alignment, not by this.
- Only the `Time | Narration` timed-script format is handled. The wiki
  `Visual Cue | Narration` format is a separate reader.

---

## The pipeline

`parse -> translate -> synthesise -> align -> timeline -> QA -> export`, running
end to end today with the hard stages faked:

```bash
python -m app.run "../Timed-script-sample-english.docx" --language en --duration 663.2 --out ../out
python -m app.run "../Tamil-script-sample.docx" --language ta --duration 663.2 --out ../out
```

That writes 95 WAV clips, an SRT and a project manifest per language, and
prints the QA report. Every run names the stubs still in the chain, so no demo
leaves anyone unsure which numbers are real.

### Why stubs first

Built module by module, the 24 September MVP arrives as four polished stages
and nothing to show. So the chain runs from day one with the intelligence
faked, and each fake is replaced behind its interface:

| stage | today | replaced by |
|---|---|---|
| translate | `EchoTranslator` - text unchanged | Module 2, duration-constrained LLM translation |
| synthesise | `SilentTTS` - silence of exactly the predicted length | Piper locally, then Sarvam AI |
| align | `ClipBoundsAligner` - the clip's own bounds | WhisperX / MFA on real audio |
| timeline | anchor at each segment start | hold insertion at non-action gaps |
| export | SRT (real) + JSON manifest | OpenTimelineIO / Kdenlive XML |

The interfaces are in `app/pipeline/interfaces.py` and every provider is
resolved by name through `app/pipeline/registry.py` - so switching provider is
configuration, not code (HLD UC-07), and the team works in parallel against
fixed shapes.

### What the stub run already tells you

The echo run reproduces Module 1's analysis exactly - 42 of 95 English
segments over budget, 83 of 95 Tamil, 536 s against 770 s of audio - which is
the point: it is a baseline known to be right, so a real translator's
improvement is measurable rather than asserted.

The English SRT shows subtitles overlapping wherever a segment overruns its
window. That is honest: it is what the timed script asks for and nothing has
fitted the text yet.

### Not done here

- Holds are not inserted; `hold_after` is always 0.
- Drift is `actual - budget`, not drift against the base video. It becomes the
  real thing when forced alignment lands.
- No API and no UI yet - the runner is a library plus a CLI, with a progress
  hook (`ProgressHook`) shaped for the job-progress endpoint.

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

The videos are gitignored (large, and not ours to redistribute), so
`tests/test_media.py` skips rather than fails when they are absent.

### Validating a track by eye

The strongest check available on the pipeline needs no toolchain at all:

```bash
python -m app.run "../Timed-script-sample-english.docx" --language en \
    --video ../Overview-of-Synfig-English.webm --out ../out
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
