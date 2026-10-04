"""FittingTranslator - Module 2, the duration-constrained translator.

The premise of the whole project, in one loop: the video cannot move and the
segment boundaries cannot move, so when a translation is too long it is the
TEXT that gives, not the speaking rate.

    budget (s)  ->  target units  ->  ask the model
                                          |
                                   measure it OURSELVES
                                          |
                       over? -> tell it by how much -> ask again
                                          |
                              fits -> keep it
                                          |
                   still over after the cap -> escalate to the author

Two details carry most of the weight.

The model is never trusted to count. Language models are poor at counting
syllables and will happily assert that an over-long line fits; every candidate
is measured with the same counter that calibrated the duration model against
the client's own recordings, and that measurement is the only one that decides.

The budget is RateModel.speaking_budget, not the segment's window. The window
includes the pause the narrator has to leave at the end of the line (Step 1).
Handing that pause to the translator produces a track where every line fits and
none of them breathe - which is the delivery the client complained about.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..duration.model import DRIFT_TOLERANCE, RateModel
from ..duration.syllables import count_syllables
from ..schemas import Segment, TranslatedSegment
from .cache import TranslationCache
from .llm import ChatModel, LLMError
from .prompts import (
    PROMPT_VERSION,
    build_first_request,
    build_retry_request,
    build_system_prompt,
    clean_reply,
)

DEFAULT_MAX_ATTEMPTS = 3
"""Rephrasing rounds before a segment is escalated. Calls are metered, and a
segment three rounds could not fit is one that needs meaning removed - which is
the author's decision to make, not the model's."""


@dataclass
class Attempt:
    """One round trip, kept so the author can see how the model got here."""

    text: str
    units: int
    predicted_duration: float
    from_cache: bool = False


@dataclass
class FittingTranslator:
    """Translates each segment under its speaking budget, retrying until it fits."""

    model: ChatModel
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    temperature: float = 0.3
    cache: TranslationCache = field(default_factory=TranslationCache)
    tolerance: float = DRIFT_TOLERANCE

    name: str = "fitting"

    def __post_init__(self) -> None:
        self.name = f"fitting:{getattr(self.model, 'name', 'unknown')}"

    def flush(self) -> None:
        """Persist the cache. Called by the runner when the stage finishes."""
        self.cache.save()

    def target_units(self, segment: Segment, target_language: str, rates: RateModel) -> int:
        """How many syllables/aksharas fit in this segment's speaking budget.

        Floored, not rounded: at a budget of 14.9 units, 15 is already over.
        Being one unit short costs nothing; being one over misses the slot.
        """
        budget = rates.speaking_budget(segment)
        return max(int(math.floor(budget * rates.rate(target_language))), 1)

    def _ask(
        self,
        system: str,
        user: str,
        *,
        source: str,
        language: str,
        target: int,
        attempt: int,
    ) -> tuple[str, bool]:
        # The prompt version is part of the model identity: change the wording
        # and the cached answers were produced by a different instruction.
        key = TranslationCache.key(
            source,
            language,
            target,
            f"{getattr(self.model, 'name', '?')}/p{PROMPT_VERSION}",
            attempt,
        )
        cached = self.cache.get(key)
        if cached is not None:
            return cached, True

        reply = clean_reply(self.model.complete(system, user, temperature=self.temperature))
        if reply:
            self.cache.put(key, reply)
        return reply, False

    def translate(
        self, segment: Segment, *, target_language: str, model: RateModel
    ) -> TranslatedSegment:
        rates = model
        target = self.target_units(segment, target_language, rates)
        budget = rates.speaking_budget(segment)
        system = build_system_prompt(target_language)

        attempts: list[Attempt] = []
        user = build_first_request(
            segment.text, target_language, target, segment.bold_terms
        )
        error: str | None = None

        for index in range(self.max_attempts):
            try:
                reply, cached = self._ask(
                    system,
                    user,
                    source=segment.text,
                    language=target_language,
                    target=target,
                    attempt=index,
                )
            except LLMError as exc:
                error = str(exc)
                break

            if not reply:
                error = "provider returned an empty translation"
                break

            units = count_syllables(reply)
            attempts.append(
                Attempt(
                    text=reply,
                    units=units,
                    predicted_duration=units / rates.rate(target_language),
                    from_cache=cached,
                )
            )
            if units <= target:
                break

            user = build_retry_request(
                segment.text,
                target_language,
                target,
                reply,
                units,
                segment.bold_terms,
            )

        if not attempts:
            # Nothing usable came back. Fail loudly rather than emitting the
            # English source as if it were a translation.
            return TranslatedSegment(
                segment_id=segment.id,
                language=target_language,
                source_text=segment.text,
                text="",
                syllables=0,
                predicted_duration=0.0,
                budget=budget,
                attempts=0,
                fitted=False,
                translator=self.name,
                note=error or "no candidate produced",
            )

        # The shortest candidate that fits; failing that, the closest one - so
        # an escalated segment shows the author the model's best effort rather
        # than whatever it happened to say last.
        best = min(attempts, key=lambda a: (max(a.units - target, 0), a.units))
        fitted = best.predicted_duration - budget <= self.tolerance

        note = None
        if not fitted:
            over = best.units - target
            unit_word = "unit" if over == 1 else "units"
            note = (
                f"still {over} {unit_word} over after {len(attempts)} attempt(s); "
                f"needs an author decision"
            )

        return TranslatedSegment(
            segment_id=segment.id,
            language=target_language,
            source_text=segment.text,
            text=best.text,
            syllables=best.units,
            predicted_duration=best.predicted_duration,
            budget=budget,
            attempts=len(attempts),
            fitted=fitted,
            translator=self.name,
            note=note,
        )
