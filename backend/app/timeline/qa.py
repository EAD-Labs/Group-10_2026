"""The QA report: the objective numbers that gate approval and export.

HLD S14 sets two thresholds, and this module exists so both are measured
rather than eyeballed:

  * per-segment drift <= 250 ms  (DRIFT_TOLERANCE)
  * mean speaking rate within +/-10% of the reference pace, and no segment
    beyond +/-15%  (RATE_TOLERANCE)

Drift here is `actual - budget`, where budget is the SPEAKING budget from
Step 1 - the window less the pause the narrator must leave. Positive drift
therefore means the narration has started eating its own pause, not merely
that it approached the next line.

Drift alone is not enough, which is the lesson of the client's Tamil track:
every one of its segments lands inside its window, and it still sounds rushed,
because the pauses were spent to get there. So each row also reports
`pause_after`, and a segment is only `unrushed` when it fits AND leaves an
audible gap.
"""

from __future__ import annotations

from ..duration.model import DRIFT_TOLERANCE, RateModel
from ..schemas import (  # noqa: F401
    AlignmentResult,
    AudioAsset,
    ParsedScript,
    QAReport,
    SegmentQA,
    TranslatedSegment,
)


def build_qa_report(
    script: ParsedScript,
    translations: list[TranslatedSegment],
    audio: list[AudioAsset],
    alignments: list[AlignmentResult],
    language: str,
    model: RateModel | None = None,
) -> QAReport:
    model = model or RateModel()
    reference = model.rate(model.reference_language)

    by_translation = {t.segment_id: t for t in translations}
    by_audio = {a.segment_id: a for a in audio}
    by_alignment = {a.segment_id: a for a in alignments}

    rows: list[SegmentQA] = []
    for segment in script.segments:
        translated = by_translation.get(segment.id)
        if translated is None:
            continue

        alignment = by_alignment.get(segment.id)
        asset = by_audio.get(segment.id)
        actual = (
            alignment.speech_duration
            if alignment
            else (asset.duration if asset else 0.0)
        )

        budget = translated.budget
        drift = actual - budget
        # Measured against the whole window, not against the speaking budget:
        # this is the silence a listener actually gets before the next line.
        pause_after = max(segment.narration_budget - actual, 0.0)
        # Rate is measured against the speech that was actually produced, not
        # against the prediction - a stub that lies about its own length would
        # otherwise report a perfect ratio.
        rate_ratio = (translated.syllables / actual / reference) if actual > 0 else 0.0

        rows.append(
            SegmentQA(
                segment_id=segment.id,
                budget=budget,
                predicted=translated.predicted_duration,
                actual=actual,
                drift=drift,
                pause_after=pause_after,
                rate_ratio=rate_ratio,
                # Only overrun breaks sync. Every clip is anchored at its own
                # start time, so narration that finishes early leaves silence
                # before the next anchor - a gap for Step 3 to fill with a
                # hold, not a segment out of sync.
                within_drift=drift <= DRIFT_TOLERANCE,
            )
        )

    return QAReport(language=language, segments=rows, reference_rate=reference)
