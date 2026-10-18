"""FittingTranslator - Module 2, the duration-constrained translator.

The premise of the whole project, in one loop: the video cannot move and the
segment boundaries cannot move, so when a translation is too long it is the
TEXT that gives, not the speaking rate.

    budget (s)  ->  target units  ->  first candidate
                                          |
                                   measure it OURSELVES
                                          |
                       over? -> tell the LLM by how much -> ask again
                                          |
                              fits -> keep it
                                          |
                   still over after the cap -> escalate to the author

The first candidate comes from one of two places. With a `drafter` (a local MT
model - IndicTrans2), it is the machine translation: a draft that fits and keeps
its on-screen terms is kept with NO LLM call, and anything else goes to the LLM
to be EDITED into the budget. Without one, the LLM translates from scratch, as
it always did.

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
from typing import Iterable, Protocol, runtime_checkable

from ..duration.model import DRIFT_TOLERANCE, RateModel
from ..schemas import Segment, TranslatedSegment
from .cache import TranslationCache
from .llm import ChatModel, LLMError
from .terms import TERMS_LOST, has_placeholder
from .prompts import (
    PROMPT_VERSION,
    build_edit_request,
    build_editor_system_prompt,
    build_first_request,
    build_retry_request,
    build_system_prompt,
    clean_reply,
    missing_terms,
)

DEFAULT_MAX_ATTEMPTS = 3
"""LLM rounds before a segment is escalated. Calls are metered, and a segment
three rounds could not fit is one that needs meaning removed - which is the
author's decision to make, not the model's."""

EDIT_PROMPT_VERSION = 1
"""Versions the edit-path wording, as PROMPT_VERSION does the direct path."""


@runtime_checkable
class Drafter(Protocol):
    """Produces a first-draft translation - typically a local MT model.

    May also offer `prepare(segments, target_language)` to work over a whole
    track at once; the translator forwards it when present."""

    name: str

    def draft(self, segment: Segment, target_language: str) -> str: ...


@dataclass
class Attempt:
    """One candidate, kept so the author can see how the loop got here."""

    text: str
    units: int
    predicted_duration: float
    from_cache: bool = False
    is_draft: bool = False
    missing: int = 0
    """On-screen terms absent from this candidate."""


@dataclass
class FittingTranslator:
    """Translates each segment under its speaking budget, retrying until it fits."""

    model: ChatModel
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    temperature: float = 0.3
    cache: TranslationCache = field(default_factory=TranslationCache)
    tolerance: float = DRIFT_TOLERANCE
    drafter: Drafter | None = None

    name: str = "fitting"

    def __post_init__(self) -> None:
        model = getattr(self.model, "name", "unknown")
        if self.drafter is not None:
            self.name = f"fitting:{self.drafter.name}+{model}"
        else:
            self.name = f"fitting:{model}"

    def flush(self) -> None:
        """Persist the cache. Called by the runner when the stage finishes."""
        self.cache.save()

    def prepare(self, segments: Iterable[Segment], target_language: str) -> None:
        """Let the drafter work over the whole track at once - batched MT is
        several times faster on CPU than one segment at a time. Called by the
        runner before the per-segment loop; optional, as drafts are cached."""
        prepare = getattr(self.drafter, "prepare", None)
        if callable(prepare):
            prepare(list(segments), target_language)

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
        draft: str | None = None,
    ) -> tuple[str, bool]:
        # The prompt version is part of the model identity: change the wording
        # and the cached answers were produced by a different instruction. On
        # the edit path the draft is part of the question, so it is part of
        # the key - a different MT draft must not return an old edit.
        identity = f"{getattr(self.model, 'name', '?')}/p{PROMPT_VERSION}"
        if draft is not None:
            identity += f"/edit{EDIT_PROMPT_VERSION}"
            source = f"{source}\x00{draft}"
        key = TranslationCache.key(source, language, target, identity, attempt)
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
        terms = segment.bold_terms

        def candidate(text: str, *, cached: bool = False, is_draft: bool = False) -> Attempt:
            units = round(rates.units(text, target_language))
            return Attempt(
                text=text,
                units=units,
                predicted_duration=units / rates.rate(target_language),
                from_cache=cached,
                is_draft=is_draft,
                # A placeholder that survived restore is as broken as a lost
                # term: it would be read aloud as "TERMX21".
                missing=len(missing_terms(text, terms)) + has_placeholder(text),
            )

        attempts: list[Attempt] = []
        error: str | None = None

        draft: str | None = None
        if self.drafter is not None:
            try:
                draft = clean_reply(self.drafter.draft(segment, target_language)) or None
            except Exception as exc:  # noqa: BLE001 - a failed draft falls back to the LLM
                error = f"draft failed: {exc}"
            if draft:
                first = candidate(draft, is_draft=True)
                attempts.append(first)
                if first.units <= target and not first.missing:
                    # Fits and keeps its terms: no LLM call at all.
                    return self._result(segment, target_language, budget, target, attempts, draft)

        if draft:
            system = build_editor_system_prompt(target_language)
            user = build_edit_request(
                segment.text,
                target_language,
                target,
                draft,
                attempts[0].units,
                terms,
                missing_terms(draft, terms),
            )
        else:
            system = build_system_prompt(target_language)
            user = build_first_request(segment.text, target_language, target, terms)

        for index in range(self.max_attempts):
            try:
                reply, cached = self._ask(
                    system,
                    user,
                    source=segment.text,
                    language=target_language,
                    target=target,
                    attempt=index,
                    draft=draft,
                )
            except LLMError as exc:
                error = str(exc)
                break

            if not reply:
                error = "provider returned an empty translation"
                break

            latest = candidate(reply, cached=cached)
            attempts.append(latest)
            if latest.units <= target:
                break

            user = build_retry_request(
                segment.text,
                target_language,
                target,
                reply,
                latest.units,
                terms,
            )

        return self._result(segment, target_language, budget, target, attempts, draft, error)

    def _result(
        self,
        segment: Segment,
        target_language: str,
        budget: float,
        target: int,
        attempts: list[Attempt],
        draft: str | None,
        error: str | None = None,
    ) -> TranslatedSegment:
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
                draft_text=draft,
                stage="failed",
                note=error or "no candidate produced",
            )

        # The shortest candidate that fits; failing that, the closest one - so
        # an escalated segment shows the author the best effort rather than
        # whatever was said last. Among equally good candidates, one that kept
        # its on-screen terms beats one that lost them.
        best = min(attempts, key=lambda a: (max(a.units - target, 0), a.missing > 0, a.units))
        fitted = best.predicted_duration - budget <= self.tolerance

        note = None
        if not fitted:
            over = best.units - target
            unit_word = "unit" if over == 1 else "units"
            note = (
                f"still {over} {unit_word} over after {len(attempts)} attempt(s); "
                f"needs an author decision"
            )
            if error:
                note += f" ({error})"
        if best.missing:
            lost = ", ".join(missing_terms(best.text, segment.bold_terms))
            note = (note + "; " if note else "") + f"{TERMS_LOST}: {lost}"

        if not fitted:
            stage = "escalated"
        elif best.is_draft:
            stage = "draft"
        elif draft is not None:
            stage = "shortened"
        else:
            stage = None

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
            draft_text=draft,
            stage=stage,
            note=note,
        )
