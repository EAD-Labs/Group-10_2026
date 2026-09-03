# Modules 1 & 4a - Script Parsing and Audio Measurement

Turns a Spoken Tutorial timed script into segments, action cues and per-segment
time budgets, validated against the Dubbers' Checklist.

## Run it

```bash
cd backend
python -m app.cli "../Timed-script-sample-english.docx" --language en --duration 663.2
python -m app.cli "../Tamil-script-sample.docx" --language ta --duration 663.2
python tests/test_parser.py        # or: pytest tests
```

`--duration` is the length of the base video. It sets the last segment's budget;
without it the parser assumes the script's median window.

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
