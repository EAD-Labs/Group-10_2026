"""The QA report: the objective numbers that gate approval and export.

HLD S14 sets two thresholds, and this module exists so both are measured
rather than eyeballed:

  * per-segment drift <= 250 ms  (DRIFT_TOLERANCE)
  * mean speaking rate within +/-10% of the reference pace, and no segment
    beyond +/-15%  (RATE_TOLERANCE)

Drift here is `actual - budget`: how far the synthesised narration runs past
the window the timed script gave it. It is reported signed, because the
negative case is useful - that is the slack Step 3 turns into holds - but only
overrun counts as a sync failure. Once real audio and a real aligner are in
place (Step 1), this becomes drift against the base video's action cues, which
is the figure the client's editors care about. The definition tightens; the
report's shape does not.
"""

from __future__ import annotations

from ..duration.model import DRIFT_TOLERANCE, RateModel
from ..schemas import (
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
                rate_ratio=rate_ratio,
                over_budget=drift > DRIFT_TOLERANCE,
                # Only overrun breaks sync. Every clip is anchored at its own
                # start time, so narration that finishes early leaves silence
                # before the next anchor - a gap for Step 3 to fill with a
                # hold, not a segment out of sync.
                within_drift=drift <= DRIFT_TOLERANCE,
            )
        )

    return QAReport(language=language, segments=rows, reference_rate=reference)
