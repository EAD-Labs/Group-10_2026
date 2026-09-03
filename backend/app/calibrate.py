"""Calibrate the duration model against a delivered tutorial.

    python -m app.calibrate --script ../Timed-script-sample-english.docx \
                            --video  ../Overview-of-Synfig-English.webm \
                            --language en

Given a script and the recording that was made from it, reports the narrator's
real articulation rate and pause behaviour - the numbers app/duration/model.py
is built on.
"""

from __future__ import annotations

import argparse
import os
import sys

from .duration.measure import calibrate, measure_script
from .media.audio import extract_audio
from .media.vad import detect_speech
from .parsing.parser import parse_script


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--work-dir", default="../work/audio")
    parser.add_argument("--show", type=int, default=0, help="Print N per-segment rows")
    args = parser.parse_args(argv)

    stem = os.path.splitext(os.path.basename(args.video))[0]
    wav = os.path.join(args.work_dir, f"{stem}.wav")

    print(f"extracting audio -> {wav}")
    extract_audio(args.video, wav)

    track = detect_speech(wav)
    print(f"  {track.duration:.1f}s of audio, speech threshold {track.threshold_db:.1f} dB")
    print(f"  {track.speech_seconds:.1f}s speech / "
          f"{track.duration - track.speech_seconds:.1f}s silence overall")
    print()

    duration = args.duration if args.duration is not None else track.duration
    script = parse_script(args.script, language=args.language, duration=duration)
    result = calibrate(script, track)

    print(f"{script.source}  [{script.language}]")
    print(f"  segments measured        : {result.segments_measured} "
          f"({len(script.segments) - result.segments_measured} skipped - embedded clips)")
    print(f"  articulation rate        : {result.articulation_rate:.2f} syl/s (median)")
    print(f"                             {result.aggregate_rate:.2f} syl/s (aggregate)")
    print(f"  median trailing pause    : {result.pause_median:.2f}s")
    print(f"  segments with no pause   : {result.segments_without_pause} "
          f"/ {result.segments_measured}")
    print(f"  window actually spoken   : {result.speech_fraction * 100:.1f}%")

    if args.show:
        print()
        print(f"  {'id':<8}{'window':>8}{'speech':>8}{'pause':>7}{'syl':>6}{'syl/s':>7}")
        for m in measure_script(script, track)[: args.show]:
            print(f"  {m.segment_id:<8}{m.window:8.1f}{m.speech:8.2f}"
                  f"{m.trailing_pause:7.2f}{m.syllables:6d}{m.articulation_rate:7.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
