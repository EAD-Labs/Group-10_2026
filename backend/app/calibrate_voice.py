"""Measure how fast a TTS voice actually speaks, at one or more paces.

    python -m app.calibrate_voice --script ../samples/Timed-script-sample-english.docx
    python -m app.calibrate_voice --script ../samples/Timed-script-sample-english.docx \
        --paces 1.0 0.9 0.8 0.7 --speaker shubh

The duration model budgets text at a rate in syllables (aksharas) per second.
A synthetic voice has its own rate, and a different one at every pace, so it is
measured on real lines with the same VAD aligner the pipeline uses.

What is measured is the SPAN of each clip - first word to last - because that
is what the QA report holds against the budget. The first version measured
speech-only seconds, which leave out the pauses inside a line (between its
sentences, at commas); every rate came out 5-9% optimistic, and at pace 0.8
eleven lines that "fit" on paper overran in the audio.

Lines are sampled across the whole length range, not just the longest: long
lines spread their pauses over more words and speak faster than the typical
line the budget has to fit.

The only input is the ENGLISH script. Its lines are translated by our own
IndicTrans2 drafter - the same text the pipeline will hand the voice - so no
human translation or dub is involved at any point. The drafts are cached from
earlier runs, so this costs only the TTS calls: one per line per pace, once.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .duration.model import VOICE_RATES_PATH, voice_key
from .duration.syllables import count_syllables
from .align.vad import VadAligner
from .parsing.parser import parse_script
from .pipeline.registry import DEFAULT_CACHE_PATH
from .schemas import TranslatedSegment
from .translate.cache import TranslationCache
from .translate.indictrans import IndicTransMT
from .tts.sarvam import SarvamTTS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate a TTS voice's speaking rate.")
    parser.add_argument("--script", required=True, help="the ENGLISH timed script")
    parser.add_argument("--language", default="ta", help="target language to calibrate")
    parser.add_argument("--speaker", default=None)
    parser.add_argument("--model", default=None, help="Sarvam model, e.g. bulbul:v3")
    parser.add_argument("--paces", type=float, nargs="+", default=[1.0])
    parser.add_argument("--segments", type=int, default=20)
    parser.add_argument("--out", default=os.path.join("out", "voice-calibration"))
    parser.add_argument("--rates", default=VOICE_RATES_PATH)
    args = parser.parse_args(argv)

    script = parse_script(args.script, language="en")
    # Evenly spaced across the length range of ordinary narration lines. Lines
    # with action cues are not typical narration; very short ones are mostly
    # lead-in.
    pool = sorted(
        (s for s in script.segments if not s.cue_ids and s.syllables >= 6),
        key=lambda s: s.syllables,
    )
    step = max(len(pool) / max(args.segments, 1), 1.0)
    chosen = [pool[int(i * step)] for i in range(min(args.segments, len(pool)))]
    if not chosen:
        print("  no usable segments in this script")
        return 1

    cache = TranslationCache(DEFAULT_CACHE_PATH)
    mt = IndicTransMT(cache=cache)
    mt.prepare(script.segments, args.language)  # builds the glossary; cached drafts
    cache.save()
    texts = {s.id: mt.draft(s, args.language) for s in chosen}

    rates: dict = {}
    if os.path.exists(args.rates):
        with open(args.rates, encoding="utf-8") as handle:
            rates = json.load(handle)

    tts = SarvamTTS(model=args.model, speaker=args.speaker)
    aligner = VadAligner()
    print(f"  {tts.name} / {tts.speaker}  [{args.language}]  {len(chosen)} lines "
          f"from {os.path.basename(args.script)} via {mt.name}")
    summary = []
    for pace in args.paces:
        tts.pace = pace
        units = 0
        speech = 0.0
        for segment in chosen:
            text = texts[segment.id]
            translated = TranslatedSegment(
                segment_id=segment.id,
                language=args.language,
                source_text=segment.text,
                text=text,
                syllables=count_syllables(text),
            )
            asset = tts.synthesize(
                translated,
                out_path=os.path.join(args.out, f"pace-{pace:.2f}", f"{segment.id}.wav"),
            )
            seconds = aligner.align(asset, text).speech_duration
            if seconds > 0:
                units += translated.syllables
                speech += seconds
        if speech <= 0:
            print(f"  pace {pace:.2f}: no speech detected - check the key and the voice")
            return 1
        rate = units / speech
        key = voice_key(tts.name, tts.speaker, pace)
        rates.setdefault(key, {})[args.language] = round(rate, 3)
        summary.append((pace, rate, key))
        print(f"    pace {pace:.2f}: {rate:.2f} units/s")

    os.makedirs(os.path.dirname(os.path.abspath(args.rates)), exist_ok=True)
    with open(args.rates, "w", encoding="utf-8") as handle:
        json.dump(rates, handle, indent=2)

    print()
    for pace, rate, key in summary:
        print(f"  {key}: {rate:.2f} units/s")
    print(f"  saved to {args.rates}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
