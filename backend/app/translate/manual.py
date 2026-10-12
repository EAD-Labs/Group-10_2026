"""ManualTranslator - the reviewer's own wording, measured like any other.

When a segment is escalated, a person decides what meaning goes (HLD S6.1 M2).
Their text then has to flow through the same pipeline - synthesis, alignment,
QA - as a generated one, so it enters as a translator: one that returns what
it was given, and still does the honest bookkeeping of whether it fits.
"""

from __future__ import annotations

from ..duration.model import DRIFT_TOLERANCE, RateModel
from ..duration.syllables import count_syllables
from ..schemas import Segment, TranslatedSegment


class ManualTranslator:
    name = "manual"

    def __init__(self, texts: dict[str, str], previous: dict[str, TranslatedSegment] | None = None):
        self.texts = texts
        self.previous = previous or {}

    def translate(
        self, segment: Segment, *, target_language: str, model: RateModel
    ) -> TranslatedSegment:
        text = " ".join(self.texts[segment.id].split())
        predicted = model.estimate(text, target_language)
        budget = model.speaking_budget(segment)
        fitted = predicted - budget <= DRIFT_TOLERANCE
        earlier = self.previous.get(segment.id)
        return TranslatedSegment(
            segment_id=segment.id,
            language=target_language,
            source_text=segment.text,
            text=text,
            syllables=count_syllables(text),
            predicted_duration=predicted,
            budget=budget,
            attempts=0,
            fitted=fitted,
            translator=self.name,
            draft_text=earlier.draft_text if earlier else None,
            stage=None if fitted else "escalated",
            note=None if fitted else f"edited text is still {predicted - budget:.1f}s over",
        )
