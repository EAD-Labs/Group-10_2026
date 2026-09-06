"""EchoTranslator - the translation stub.

Returns the source text unchanged. It exists so the pipeline runs end to end
before Module 2 exists, and so the stage that replaces it has something to be
measured against: echoing English into an English track is the identity case,
where predicted duration should equal the reference track's own.

It still does the honest bookkeeping - syllable count, predicted duration,
budget, and whether that fits - so the QA report is meaningful today and the
'unfittable segment' escalation path is exercised before a real translator
ever runs. Budgets and durations both come from the Step 1 model, measured
from the client's own recordings, so the stub's numbers are comparable with
what a real translator will be scored against.
"""

from __future__ import annotations

from ..duration.model import DRIFT_TOLERANCE, RateModel
from ..duration.syllables import count_syllables
from ..schemas import Segment, TranslatedSegment


class EchoTranslator:
    """Passes text through untouched."""

    name = "echo"

    def translate(
        self, segment: Segment, *, target_language: str, model: RateModel
    ) -> TranslatedSegment:
        text = segment.text
        predicted = model.estimate(text, target_language)
        # Step 1's budget, not the raw window: the window includes the pause
        # the narrator has to leave at the end of the line, and handing that
        # to the translator as speaking time is what produced a track where
        # every segment "fits" and nothing has room to breathe.
        budget = model.speaking_budget(segment)
        return TranslatedSegment(
            segment_id=segment.id,
            language=target_language,
            source_text=segment.text,
            text=text,
            syllables=count_syllables(text),
            predicted_duration=predicted,
            budget=budget,
            attempts=1,
            # A stub cannot rephrase, so anything over budget is reported as
            # unfitted rather than quietly passed on. Against the measured
            # articulation rate this flags 63 of 95 Tamil segments - which is
            # the problem, stated.
            fitted=predicted - budget <= DRIFT_TOLERANCE,
            translator=self.name,
        )
