"""Measure how fast a TTS voice actually speaks, at one or more paces.

    python -m app.calibrate_voice --script ../samples/Timed-script-sample-english.docx
    python -m app.calibrate_voice --script ../samples/Timed-script-sample-english.docx         --paces 1.0 0.9 0.8 0.7 --speaker shubh --language hi

The pipeline calibrates on its own the first time it meets a voice, language
and pace it has no rate for (the `calibrate` stage), so this is only needed to
measure ahead of time. How and why: app/duration/calibrate.py. The only input
is the ENGLISH script.
"""

from __future__ import annotations

import argparse
import os
import sys

from .align.vad import VadAligner
from .duration.calibrate import SAMPLE_LINES, calibrate
from .duration.model import VOICE_RATES_PATH, voice_key
from .parsing.parser import parse_script
from .pipeline.registry import DEFAULT_CACHE_PATH
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
    parser.add_argument("--segments", type=int, default=SAMPLE_LINES)
    parser.add_argument("--out", default=os.path.join("out", "voice-calibration"))
    parser.add_argument("--rates", default=VOICE_RATES_PATH)
    args = parser.parse_args(argv)

    script = parse_script(args.script, language="en")
    cache = TranslationCache(DEFAULT_CACHE_PATH)
    mt = IndicTransMT(cache=cache)
    tts = SarvamTTS(model=args.model, speaker=args.speaker)
    aligner = VadAligner()
    print(f"  {tts.name} / {tts.speaker}  [{args.language}]  "
          f"{args.segments} lines from {os.path.basename(args.script)} via {mt.name}")

    summary = []
    for pace in args.paces:
        tts.pace = pace
        key = voice_key(tts.name, tts.speaker, pace)
        rate = calibrate(
            script.segments, args.language, tts, aligner, mt,
            key=key,
            out_dir=os.path.join(args.out, args.language, f"pace-{pace:.2f}"),
            count=args.segments,
            rates_path=args.rates,
        )
        cache.save()
        if not rate:
            print(f"  pace {pace:.2f}: no speech detected - check the key and the voice")
            return 1
        summary.append((key, rate))
        print(f"    pace {pace:.2f}: {rate:.2f} units/s")

    print()
    for key, rate in summary:
        print(f"  {key}: {rate:.2f} units/s")
    print(f"  saved to {args.rates}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
