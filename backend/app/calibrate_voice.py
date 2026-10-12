"""Measure how fast a TTS voice actually speaks, and save it for budgeting.

    python -m app.calibrate_voice --script ../samples/Tamil-script-sample.docx --language ta
    python -m app.calibrate_voice --script ../samples/Tamil-script-sample.docx --language ta \
        --speaker vidya --segments 20

The duration model budgets text at a rate in syllables (aksharas) per second.
The default rates were measured on the client's human narrator; a Bulbul voice
speaks at its own pace. If the two disagree, every "fits" the translator
reports is wrong by the same factor - so the voice is measured the way Step 1
measured the narrator: synthesise real lines, find the speech with the same
VAD, divide.

Calibrated on the client's own Tamil text, because the point is the voice's
pace on this register of narration, not on arbitrary sentences. Costs one TTS
call per segment, once; the clips are cached.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .duration.model import VOICE_RATES_PATH, voice_key
from .duration.syllables import count_syllables
from .media.vad import detect_speech
from .parsing.parser import parse_script
from .schemas import TranslatedSegment
from .tts.sarvam import SarvamTTS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate a TTS voice's speaking rate.")
    parser.add_argument("--script", required=True, help="a script in the target language")
    parser.add_argument("--language", default="ta")
    parser.add_argument("--speaker", default=None)
    parser.add_argument("--model", default=None, help="Sarvam model, e.g. bulbul:v2")
    parser.add_argument("--segments", type=int, default=15)
    parser.add_argument("--out", default=os.path.join("out", "voice-calibration"))
    parser.add_argument("--rates", default=VOICE_RATES_PATH)
    args = parser.parse_args(argv)

    tts = SarvamTTS(model=args.model, speaker=args.speaker)
    script = parse_script(args.script, language=args.language)

    # Long, plain lines: short ones are dominated by the clip's lead-in, and
    # lines with action cues are not typical narration.
    candidates = sorted(
        (s for s in script.segments if not s.cue_ids and s.syllables >= 12),
        key=lambda s: -s.syllables,
    )[: args.segments]
    if not candidates:
        print("  no usable segments in this script")
        return 1

    total_units = 0
    total_speech = 0.0
    print(f"  {tts.name} / {tts.speaker}  [{args.language}]  {len(candidates)} segments")
    for segment in candidates:
        translated = TranslatedSegment(
            segment_id=segment.id,
            language=args.language,
            source_text=segment.text,
            text=segment.text,
            syllables=count_syllables(segment.text),
        )
        asset = tts.synthesize(
            translated, out_path=os.path.join(args.out, f"{segment.id}.wav")
        )
        speech = detect_speech(asset.path).speech_seconds
        if speech <= 0:
            continue
        total_units += translated.syllables
        total_speech += speech
        print(f"    {segment.id}  {translated.syllables:3d} units  {speech:5.2f}s  "
              f"{translated.syllables / speech:4.2f}/s")

    if total_speech <= 0:
        print("  no speech detected - check the key and the voice")
        return 1

    rate = total_units / total_speech
    key = voice_key(tts.name, tts.speaker)
    rates: dict = {}
    if os.path.exists(args.rates):
        with open(args.rates, encoding="utf-8") as handle:
            rates = json.load(handle)
    rates.setdefault(key, {})[args.language] = round(rate, 3)
    os.makedirs(os.path.dirname(os.path.abspath(args.rates)), exist_ok=True)
    with open(args.rates, "w", encoding="utf-8") as handle:
        json.dump(rates, handle, indent=2)

    print()
    print(f"  articulation rate : {rate:.2f} units/s  (aggregate)")
    print(f"  saved to          : {args.rates}  as {key!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
