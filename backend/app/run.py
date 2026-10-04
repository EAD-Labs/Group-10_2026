"""Run the whole pipeline over a script.

    python -m app.run "../Timed-script-sample-english.docx" --language en --duration 663.2
    python -m app.run script.docx --language ta --tts silent --out out/

Stages that are still stubs are named in the output on purpose: a demo should
never leave anyone unsure which numbers are real.
"""

from __future__ import annotations

import argparse
import os
import sys

from .duration.model import (
    DRIFT_TOLERANCE,
    ENGLISH_PAUSE_MEDIAN,
    RATE_TOLERANCE,
    RateModel,
)
from .media.probe import probe
from .pipeline.registry import ALIGNERS, EXPORTERS, TRANSLATORS, TTS_PROVIDERS
from .pipeline.runner import PipelineConfig, run_pipeline

STUBS = {"echo", "silent", "clip-bounds", "manifest"}


def _progress(stage: str, done: int, total: int) -> None:
    # Flushed, and not only at completion: a translate stage is ~95 metered
    # network calls, and a run that prints nothing for ten minutes is
    # indistinguishable from a run that has hung.
    if done == total or done % 5 == 0:
        print(f"  {stage:<11} {done}/{total}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the script-to-export pipeline.")
    parser.add_argument("script")
    parser.add_argument("--language", default="en", help="target language of the track")
    parser.add_argument("--source-language", default="en")
    parser.add_argument("--duration", type=float, default=None, help="base video length (s)")
    parser.add_argument("--video", default=None,
                        help="base video; its duration is read from the container "
                             "(overrides --duration)")
    parser.add_argument("--out", default="out", help="output directory")
    parser.add_argument("--translator", default="echo", choices=sorted(TRANSLATORS))
    parser.add_argument("--tts", default="silent", choices=sorted(TTS_PROVIDERS))
    parser.add_argument("--aligner", default="clip-bounds", choices=sorted(ALIGNERS))
    parser.add_argument("--export", nargs="*", default=["srt", "manifest"],
                        choices=sorted(EXPORTERS))
    parser.add_argument("--voice", default=None)
    parser.add_argument("--max-attempts", type=int, default=None,
                        help="rephrasing rounds before a segment is escalated")
    args = parser.parse_args(argv)

    duration = args.duration
    if args.video:
        info = probe(args.video)
        duration = info.duration
        print(f"  base video   : {os.path.basename(args.video)}  {duration:.3f}s")

    if args.max_attempts is not None:
        from .pipeline import registry
        registry.DEFAULT_MAX_ATTEMPTS_OVERRIDE = args.max_attempts

    config = PipelineConfig(
        language=args.language,
        out_dir=args.out,
        translator=args.translator,
        tts=args.tts,
        aligner=args.aligner,
        exporters=list(args.export),
        voice=args.voice,
        rate_model=RateModel(),
    )

    print(f"{args.script}  ->  {args.language}")
    script, track = run_pipeline(
        args.script,
        config,
        duration=duration,
        source_language=args.source_language,
        progress=_progress,
    )

    qa = track.qa
    assert qa is not None
    print()
    print(f"  segments           : {len(track.translations)}")
    print(f"  unfitted segments  : {len(track.unfitted)}  (translator could not fit the budget)")
    print(f"  worst overrun      : {qa.max_drift:.2f}s   (threshold {DRIFT_TOLERANCE:.2f}s)")
    print(f"  segments overrunning: {len(qa.drift_failures)} / {len(qa.segments)}")
    print(f"  longest silence     : {qa.largest_gap:.2f}s   (Step 3 turns these into holds)")
    print(f"  median pause left  : {qa.median_pause:.2f}s   "
          f"(reference: English delivery leaves {ENGLISH_PAUSE_MEDIAN:.2f}s)")
    print(f"  segments w/o a pause: {qa.segments_without_pause} / {len(qa.segments)}  "
          f"(the client's Tamil dub: 50 of 84)")
    print(f"  mean rate ratio    : {qa.mean_rate_ratio:.2f}   "
          f"(target 1.00 +/-{RATE_TOLERANCE:.0%})")
    print(f"  audio written      : {sum(a.duration for a in track.audio):.1f}s "
          f"across {len(track.audio)} clips")
    escalated = track.unfitted
    if escalated:
        print()
        print(f"  NEEDS AN AUTHOR DECISION: {len(escalated)} segment(s)")
        print("  These could not be fitted by rephrasing alone - meaning has to")
        print("  come out, and that is not the model's call to make.")
        by_id = {s.id: s for s in script.segments}
        for item in sorted(escalated, key=lambda t: -t.overrun)[:10]:
            source = by_id[item.segment_id].text[:60] if item.segment_id in by_id else ""
            print()
            print(f"    {item.segment_id}  budget {item.budget:.1f}s  "
                  f"needs {item.predicted_duration:.1f}s  (+{item.overrun:.1f}s)")
            print(f"      {args.source_language.upper():<3}: {source}")
            if item.text:
                print(f"      {args.language.upper():<3}: {item.text[:60]}")
            if item.note:
                print(f"      -> {item.note}")
        if len(escalated) > 10:
            print()
            print(f"    ... and {len(escalated) - 10} more")

    print()
    for path in track.exports:
        print(f"  exported {path}")

    active_stubs = sorted(
        {args.translator, args.tts, args.aligner, *args.export} & STUBS
    )
    if active_stubs:
        print()
        print(f"  STUBBED STAGES: {', '.join(active_stubs)} - these numbers are not real audio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
