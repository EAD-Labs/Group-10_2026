"""Measure how fast a TTS voice actually speaks, from the job's own script.

The duration model budgets text at a rate in aksharas (or syllables) per
second. A synthetic voice has its own rate - a different one per language,
speaker and pace - so it is measured on real lines with the same VAD aligner
the pipeline uses, and stored under `voice_key(...)` in VOICE_RATES_PATH.

What is measured is the SPAN of each clip - first word to last - because that
is what the QA report holds against the budget. Measuring speech-only seconds
leaves out the pauses inside a line (between its sentences, at commas); every
rate came out 5-9% optimistic that way, and at pace 0.8 eleven Synfig lines
that "fit" on paper overran in the audio.

Lines are sampled across the whole length range, not just the longest: long
lines spread their pauses over more words and speak faster than the typical
line the budget has to fit.

The only input is the ENGLISH script. Its lines are translated by our own MT
drafter - the same text the pipeline will hand the voice - so no human
translation or dub is involved at any point. The drafts are needed by the
translate stage anyway, so the extra cost is one TTS call per sampled line.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Callable, Protocol

from ..schemas import Segment, TranslatedSegment
from .model import VOICE_RATES_PATH
from .syllables import spoken_units

SAMPLE_LINES = 20

_FILE_LOCK = threading.Lock()


class _Drafter(Protocol):
    def prepare(self, segments, target_language: str) -> None: ...

    def draft(self, segment: Segment, target_language: str) -> str: ...


def choose_lines(segments: list[Segment], count: int = SAMPLE_LINES) -> list[Segment]:
    """Evenly spaced across the length range of ordinary narration lines.

    Lines with action cues are not typical narration; very short ones are
    mostly lead-in."""
    pool = sorted(
        (s for s in segments if not s.cue_ids and s.syllables >= 6),
        key=lambda s: s.syllables,
    )
    if not pool:
        return []
    step = max(len(pool) / max(count, 1), 1.0)
    return [pool[int(i * step)] for i in range(min(count, len(pool)))]


def calibrated_rate(key: str, language: str, path: str = VOICE_RATES_PATH) -> float | None:
    """The stored rate for this voice and language, or None if never measured."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle).get(key, {}).get(language)
    except (OSError, ValueError, AttributeError):
        return None
    return float(value) if value and float(value) > 0 else None


def save_rate(key: str, language: str, rate: float, path: str = VOICE_RATES_PATH) -> None:
    with _FILE_LOCK:
        rates: dict = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    rates = json.load(handle)
            except (OSError, ValueError):
                rates = {}
        rates.setdefault(key, {})[language] = round(rate, 3)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(rates, handle, indent=2)


def measure_rate(
    texts: dict[str, str],
    language: str,
    tts,
    aligner,
    out_dir: str,
    progress: Callable[[int, int], None] | None = None,
) -> float | None:
    """Spoken units (app.duration.syllables.spoken_units) per second of clip
    span, over every sampled line the voice spoke - the same units the
    duration model predicts in."""
    units = 0
    span = 0.0
    total = len(texts)
    for done, (segment_id, text) in enumerate(texts.items(), start=1):
        translated = TranslatedSegment(
            segment_id=segment_id,
            language=language,
            source_text="",
            text=text,
            syllables=round(spoken_units(text, language)),
        )
        asset = tts.synthesize(translated, out_path=os.path.join(out_dir, f"{segment_id}.wav"))
        seconds = aligner.align(asset, text).speech_duration
        if seconds > 0 and translated.syllables > 0:
            units += translated.syllables
            span += seconds
        if progress:
            progress(done, total)
    return units / span if span > 0 else None


def calibrate(
    segments: list[Segment],
    language: str,
    tts,
    aligner,
    drafter: _Drafter,
    *,
    key: str,
    out_dir: str,
    count: int = SAMPLE_LINES,
    rates_path: str = VOICE_RATES_PATH,
    progress: Callable[[int, int], None] | None = None,
) -> float | None:
    """Draft, voice and measure `count` lines of this script; store the rate."""
    chosen = choose_lines(segments, count)
    if not chosen:
        return None
    drafter.prepare(segments, language)
    texts = {s.id: drafter.draft(s, language) for s in chosen}
    texts = {k: v for k, v in texts.items() if v.strip()}
    rate = measure_rate(texts, language, tts, aligner, out_dir, progress)
    if rate:
        save_rate(key, language, rate, rates_path)
    return rate
