"""Command-line report over a timed script.

    python -m app.cli <script.docx> --language ta --duration 663.2
    python -m app.cli <script.docx> --json segments.json
"""

from __future__ import annotations

import argparse
import json
import sys

from .duration.model import RateModel, calibrate_from_script, fit_track
from .media.probe import probe
from .parsing.parser import parse_script


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse a Spoken Tutorial timed script.")
    parser.add_argument("script")
    parser.add_argument("--language", default="en", help="ISO code of the script's language")
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Length of the base video in seconds (sets the last segment's budget)",
    )
    parser.add_argument(
        "--video",
        default=None,
        help="Base video; its duration is read from the container (overrides --duration)",
    )
    parser.add_argument("--json", dest="json_out", help="Write parsed segments to this file")
    parser.add_argument("--limit", type=int, default=12, help="Rows of detail to print")
    args = parser.parse_args(argv)

    duration = probe(args.video).duration if args.video else args.duration
    script = parse_script(args.script, language=args.language, duration=duration)
    fit = fit_track(script, None, args.language, RateModel())
    delivered = calibrate_from_script(script)

    print(f"{script.source}  [{script.language}]  {script.duration:.1f}s")
    print(f"  narration segments : {len(script.segments)}")
    print(f"  action cues        : {len(script.cues)}")
    print(f"  errors / warnings  : {script.error_count} / {script.warning_count}")
    print()
    print(f"  delivered pace     : {delivered:.2f} syllables/sec (median)")
    print(f"  narration budget   : {script.narration_budget_total:.1f}s of {script.duration:.1f}s")
    print(f"  reserved for clips : {sum(s.cue_reserved for s in script.segments):.1f}s")
    print(f"  usable slack       : {sum(s.trailing_slack for s in script.segments):.1f}s")
    print()
    print(f"  at the {fit.reference_rate:.2f} syl/s reference pace this text needs "
          f"{fit.total_predicted:.1f}s against {fit.total_budget:.1f}s of budget")
    print(f"  segments over budget: {len(fit.over_budget)} / {len(fit.fits)}")
    print(f"  total overrun       : {fit.total_overrun:.1f}s")

    worst = sorted(fit.fits, key=lambda f: -f.overrun)[: args.limit]
    if worst and worst[0].overrun > 0:
        print()
        print("  worst segments:")
        by_id = {s.id: s for s in script.segments}
        for item in worst:
            if item.overrun <= 0:
                break
            text = by_id[item.segment_id].text[:52]
            print(
                f"    {item.segment_id}  +{item.overrun:5.1f}s  "
                f"budget {item.budget:5.1f}s  needs {item.predicted:5.1f}s  | {text}"
            )

    errors = [(s, v) for s in script.segments for v in s.violations if v.severity == "error"]
    if errors:
        print()
        print(f"  rule violations (errors): {len(errors)}")
        for segment, violation in errors[: args.limit]:
            print(f"    {segment.id}  {violation.rule}  {violation.message[:78]}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(script.model_dump(), handle, ensure_ascii=False, indent=2)
        print()
        print(f"  wrote {args.json_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
