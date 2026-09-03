"""The duration model: how long will this text take to say?

The whole project turns on this. The client's constraint is that a translated
track must land inside the English video's timing, so we must predict spoken
duration BEFORE synthesis and rephrase until it fits - rather than discover the
overrun afterwards and make the dubber talk faster.

Rates are syllables per second, calibrated per language from a matched pair of
scripts (see calibrate_from_script).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..schemas import ParsedScript, Segment
from .syllables import count_syllables

# Measured by voice-activity analysis of the audio the client supplied for the
# Synfig "Overview and Installation" pair (app/duration/measure.py). These are
# articulation rates - syllables per second of ACTUAL SPEECH, with silence
# excluded - not syllables per second of script window.
MEASURED_ENGLISH_ARTICULATION = 3.91
MEASURED_TAMIL_ARTICULATION = 4.85
"""The Tamil figure is what the dubbing artist was forced into: 24% faster than
the English it has to fit inside. It is evidence, never a target."""

ENGLISH_PAUSE_MEDIAN = 0.41
"""Seconds of silence the English narrator leaves at the end of a segment."""

PAUSE_RESERVE = 0.40
"""Seconds withheld from every segment's budget for the pause after it.

Measured as a fixed quantity, not a proportion: across the English track the
trailing pause correlates with window length at r = 0.06, sitting near 0.4 s
whether the window is 4 s or 12 s. The client's dubbing instructions require
"an appropriate pause between sentences", so this is reserved before the
translator ever sees the budget - otherwise a translation that exactly fills
its window leaves nowhere to put the pause."""

DEFAULT_RATES = {
    "en": MEASURED_ENGLISH_ARTICULATION,
    "ta": MEASURED_ENGLISH_ARTICULATION,
    "hi": MEASURED_ENGLISH_ARTICULATION,
    "mr": MEASURED_ENGLISH_ARTICULATION,
}
"""Target rates. Every language is aimed at the English articulation rate on
purpose: the point of the project is that the TEXT absorbs the expansion, not
the speaking rate."""

DRIFT_TOLERANCE = 0.25
"""Seconds. HLD S14 acceptance criterion: per-segment drift <= 250 ms."""

RATE_TOLERANCE = 0.10
"""Speaking rate must stay within +/-10% of the reference pace (HLD S14)."""


@dataclass
class RateModel:
    rates: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_RATES))
    reference_language: str = "en"
    pause_reserve: float = PAUSE_RESERVE

    def rate(self, language: str) -> float:
        return self.rates.get(language, self.rates[self.reference_language])

    def estimate(self, text: str, language: str) -> float:
        """Predicted duration of the speech itself, excluding the pause after it."""
        return count_syllables(text) / self.rate(language)

    def speaking_budget(self, segment: Segment) -> float:
        """What the narration may occupy once the trailing pause is withheld.

        This is the number the fitting engine must target. Aiming at the full
        window produces a track where every line technically fits and nothing
        has room to breathe - which is the complaint the project exists to fix.
        """
        return max(segment.narration_budget - self.pause_reserve, 0.0)


@dataclass
class SegmentFit:
    segment_id: str
    budget: float
    predicted: float
    syllables: int

    @property
    def overrun(self) -> float:
        return self.predicted - self.budget

    @property
    def required_rate(self) -> float:
        """The pace a speaker would have to hit to fit this budget."""
        return self.syllables / self.budget if self.budget > 0 else float("inf")

    def rate_ratio(self, reference: float) -> float:
        return self.required_rate / reference

    def fits(self, tolerance: float = DRIFT_TOLERANCE) -> bool:
        return self.overrun <= tolerance


@dataclass
class TrackFit:
    language: str
    fits: list[SegmentFit]
    reference_rate: float

    @property
    def over_budget(self) -> list[SegmentFit]:
        return [f for f in self.fits if not f.fits()]

    @property
    def total_overrun(self) -> float:
        return sum(f.overrun for f in self.fits if f.overrun > 0)

    @property
    def net_overrun(self) -> float:
        return sum(f.overrun for f in self.fits)

    @property
    def total_predicted(self) -> float:
        return sum(f.predicted for f in self.fits)

    @property
    def total_budget(self) -> float:
        return sum(f.budget for f in self.fits)

    @property
    def mean_rate_ratio(self) -> float:
        ratios = [f.rate_ratio(self.reference_rate) for f in self.fits if f.budget > 0]
        return statistics.mean(ratios) if ratios else 0.0


def calibrate_from_script(script: ParsedScript) -> float:
    """Derive a language's delivered speaking rate from a finished script.

    Uses the median, not the mean: rows sitting in front of an embedded clip
    have artificially generous windows and would drag a mean downwards.
    """
    rates = [
        segment.syllables / segment.narration_budget
        for segment in script.segments
        if segment.narration_budget > 0 and segment.syllables > 0
    ]
    if not rates:
        raise ValueError(f"{script.source}: nothing to calibrate from")
    return statistics.median(rates)


def fit_segment(segment: Segment, text: str, language: str, model: RateModel) -> SegmentFit:
    return SegmentFit(
        segment_id=segment.id,
        budget=model.speaking_budget(segment),
        predicted=model.estimate(text, language),
        syllables=count_syllables(text),
    )


def fit_track(
    script: ParsedScript,
    translations: dict[str, str] | None,
    language: str,
    model: RateModel | None = None,
) -> TrackFit:
    """Score a whole language track against the base script's budgets.

    translations maps segment id -> translated text. Pass None to score the
    script against itself, which is how the reference track is measured.
    """
    model = model or RateModel()
    fits = [
        fit_segment(
            segment,
            (translations or {}).get(segment.id, segment.text),
            language,
            model,
        )
        for segment in script.segments
    ]
    return TrackFit(language=language, fits=fits, reference_rate=model.rate("en"))
