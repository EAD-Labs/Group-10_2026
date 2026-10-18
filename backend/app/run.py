"""Run the whole pipeline over a script.

    python -m app.run ../samples/Timed-script-sample-english.docx --language en --duration 663.2
    python -m app.run ../samples/Timed-script-sample-english.docx --language ta         --translator indictrans+groq --tts sarvam --aligner vad         --video ../samples/Overview-of-Synfig-English.webm --workers 4

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
from .parsing.parser import parse_script
from .pipeline.registry import ALIGNERS, EXPORTERS, TRANSLATORS, TTS_PROVIDERS
from .pipeline.runner import PipelineConfig, build_providers, run_track


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
    parser.add_argument("--export", nargs="*", default=None, choices=sorted(EXPORTERS),
                        help="deliverables (default: script, srt, manifest - and mixdown "
                             "when --video is given)")
    parser.add_argument("--voice", default=None)
    parser.add_argument("--max-attempts", type=int, default=None,
                        help="rephrasing rounds before a segment is escalated")
    parser.add_argument("--pace", type=float, default=1.0,
                        help="speaking pace for the whole track (1.0 = natural; TTS "
                             "providers that support it)")
    parser.add_argument("--workers", type=int, default=1,
                        help="concurrent provider calls in translate/synthesize")
    args = parser.parse_args(argv)

    duration = args.duration
    if args.video:
        info = probe(args.video)
        duration = info.duration
        print(f"  base video   : {os.path.basename(args.video)}  {duration:.3f}s")

    provider_options: dict[str, dict] = {}
    if args.max_attempts is not None:
        provider_options["translator"] = {"max_attempts": args.max_attempts}

    config = PipelineConfig(
        language=args.language,
        out_dir=args.out,
        translator=args.translator,
        tts=args.tts,
        aligner=args.aligner,
        exporters=list(args.export) if args.export is not None
        else ["script", "srt", "manifest"] + (["mixdown"] if args.video else []),
        voice=args.voice,
        rate_model=RateModel(),
        provider_options=provider_options,
        max_workers=args.workers,
        voice_pace=args.pace,
        video_path=args.video,
    )

    print(f"{args.script}  ->  {args.language}")
    script = parse_script(args.script, language=args.source_language, duration=duration)
    providers = build_providers(config, script)
    track = run_track(script, config, progress=_progress, providers=providers)

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

    if providers.stubs:
        print()
        print(f"  STUBBED STAGES: {', '.join(providers.stubs)} - these numbers are not real audio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
