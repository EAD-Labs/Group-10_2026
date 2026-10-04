"""Tests for Module 2 - the duration-constrained translator.

Every test drives the loop with ScriptedChat, so the branch behaviour is
exercised without a network call or a metered credit. What is being pinned down
is the loop's judgement: what it targets, what it believes, when it retries and
when it gives up.

Test fixtures are built from a 3-akshara Tamil word so a reply of a known
length can be constructed by repetition.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.duration.model import RateModel  # noqa: E402
from app.duration.syllables import count_syllables  # noqa: E402
from app.parsing.parser import parse_script  # noqa: E402
from app.pipeline.interfaces import Translator  # noqa: E402
from app.translate.cache import TranslationCache  # noqa: E402
from app.translate.fitting import FittingTranslator  # noqa: E402
from app.translate.llm import GroqChat, LLMError, ScriptedChat  # noqa: E402
from app.translate.prompts import build_first_request, clean_reply  # noqa: E402

MATERIALS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGLISH = os.path.join(MATERIALS, "Timed-script-sample-english.docx")
VIDEO_DURATION = 663.2

WORD = "வணக்கம்"  # 3 aksharas
assert count_syllables(WORD) == 3


def tamil_of(aksharas: int) -> str:
    """A Tamil string of approximately the requested akshara count."""
    return " ".join([WORD] * max(aksharas // 3, 1))


def a_segment(index: int = 1):
    script = parse_script(ENGLISH, language="en", duration=VIDEO_DURATION)
    return script.segments[index]


def test_it_satisfies_the_translator_protocol():
    assert isinstance(FittingTranslator(model=ScriptedChat()), Translator)


def test_the_target_comes_from_the_speaking_budget_not_the_window():
    """Step 1's finding, enforced at the point it actually bites.

    The window includes the pause the narrator must leave. Targeting the window
    buys back roughly two aksharas a segment, which is how a track ends up with
    every line fitting and none of them breathing."""
    segment = a_segment()
    rates = RateModel()
    translator = FittingTranslator(model=ScriptedChat())

    target = translator.target_units(segment, "ta", rates)
    window_target = int(segment.narration_budget * rates.rate("ta"))

    assert target < window_target
    assert target == int(rates.speaking_budget(segment) * rates.rate("ta"))


def test_a_translation_that_fits_is_kept_on_the_first_attempt():
    segment = a_segment()
    rates = RateModel()
    translator = FittingTranslator(model=ScriptedChat())
    target = translator.target_units(segment, "ta", rates)

    translator.model.replies = [tamil_of(target - 3)]
    result = translator.translate(segment, target_language="ta", model=rates)

    assert result.fitted is True
    assert result.attempts == 1
    assert result.syllables <= target
    assert result.note is None
    assert len(translator.model.calls) == 1


def test_an_overlong_translation_is_sent_back_with_the_shortfall():
    segment = a_segment()
    rates = RateModel()
    translator = FittingTranslator(model=ScriptedChat())
    target = translator.target_units(segment, "ta", rates)

    too_long = tamil_of(target + 12)
    translator.model.replies = [too_long, tamil_of(target - 3)]
    result = translator.translate(segment, target_language="ta", model=rates)

    assert result.attempts == 2
    assert result.fitted is True

    # The retry has to tell the model the real numbers, not just "shorter".
    retry_prompt = translator.model.calls[1][1]
    assert str(count_syllables(too_long)) in retry_prompt
    assert str(target) in retry_prompt
    assert too_long in retry_prompt


def test_a_segment_that_never_fits_is_escalated_with_its_best_attempt():
    """HLD S6.1 M2: unfittable segments go to the author, not into the track.

    The author sees the model's closest attempt rather than its last one, since
    the last is not necessarily the shortest."""
    segment = a_segment()
    rates = RateModel()
    translator = FittingTranslator(model=ScriptedChat())
    target = translator.target_units(segment, "ta", rates)

    translator.model.replies = [
        tamil_of(target + 30),
        tamil_of(target + 9),   # closest
        tamil_of(target + 21),
    ]
    result = translator.translate(segment, target_language="ta", model=rates)

    assert result.fitted is False
    assert result.attempts == 3
    assert result.note is not None and "author" in result.note
    assert result.syllables == count_syllables(tamil_of(target + 9))


def test_the_model_is_never_trusted_to_count():
    """Models assert that over-long lines fit. Only our own counter decides."""
    segment = a_segment()
    rates = RateModel()
    translator = FittingTranslator(model=ScriptedChat(), max_attempts=1)
    target = translator.target_units(segment, "ta", rates)

    translator.model.replies = [tamil_of(target + 30)]
    result = translator.translate(segment, target_language="ta", model=rates)

    assert result.fitted is False
    assert result.syllables == count_syllables(translator.model.calls and tamil_of(target + 30))


def test_an_empty_reply_never_becomes_a_translation():
    """Emitting the English source as if it were Tamil would be a silent
    failure that survives all the way to a dubbing artist."""
    segment = a_segment()
    translator = FittingTranslator(model=ScriptedChat([""]))
    result = translator.translate(segment, target_language="ta", model=RateModel())

    assert result.text == ""
    assert result.fitted is False
    assert result.text != segment.text
    assert result.note is not None


def test_a_provider_failure_escalates_rather_than_crashing_the_run():
    class Broken:
        name = "broken"

        def complete(self, system, user, *, temperature=0.3):
            raise LLMError("429 rate limited")

    result = FittingTranslator(model=Broken()).translate(
        a_segment(), target_language="ta", model=RateModel()
    )
    assert result.fitted is False
    assert "429" in (result.note or "")


def test_the_cache_stops_a_rerun_paying_twice():
    segment = a_segment()
    rates = RateModel()
    cache = TranslationCache()
    target = FittingTranslator(model=ScriptedChat()).target_units(segment, "ta", rates)

    first = FittingTranslator(model=ScriptedChat([tamil_of(target - 3)]), cache=cache)
    first.translate(segment, target_language="ta", model=rates)
    assert len(first.model.calls) == 1

    # Same model name, same source, same budget: the second run must not call out.
    second = FittingTranslator(model=ScriptedChat([tamil_of(target - 3)]), cache=cache)
    result = second.translate(segment, target_language="ta", model=rates)

    assert len(second.model.calls) == 0
    assert result.fitted is True
    assert cache.hits >= 1


def test_a_changed_budget_misses_the_cache():
    """Otherwise a re-run after a script edit returns text fitted to the old
    budget, silently."""
    segment = a_segment()
    cache = TranslationCache()
    generous = RateModel()
    tight = RateModel(pause_reserve=2.0)

    first = FittingTranslator(model=ScriptedChat([tamil_of(6)]), cache=cache)
    first.translate(segment, target_language="ta", model=generous)

    second = FittingTranslator(model=ScriptedChat([tamil_of(6)]), cache=cache)
    second.translate(segment, target_language="ta", model=tight)

    assert len(second.model.calls) == 1


def test_the_cache_survives_the_process_that_paid_for_it():
    """A cache held only in memory means the next run re-pays for all 95
    segments. It has to reach disk, and it has to reload."""
    import tempfile

    segment = a_segment()
    rates = RateModel()
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "cache", "translations.json")
        target = FittingTranslator(model=ScriptedChat()).target_units(segment, "ta", rates)

        first = FittingTranslator(
            model=ScriptedChat([tamil_of(target - 3)]), cache=TranslationCache(path)
        )
        first.translate(segment, target_language="ta", model=rates)
        first.flush()
        assert os.path.exists(path)

        # A fresh process: new cache object, same file.
        second = FittingTranslator(
            model=ScriptedChat([tamil_of(target - 3)]), cache=TranslationCache(path)
        )
        result = second.translate(segment, target_language="ta", model=rates)

        assert len(second.model.calls) == 0
        assert result.fitted is True


def test_a_prompt_change_invalidates_cached_translations():
    """Cached text was produced by a particular instruction. Change the
    instruction and the old answers are no longer answers to this question."""
    from app.translate import prompts

    segment = a_segment()
    rates = RateModel()
    cache = TranslationCache()
    target = FittingTranslator(model=ScriptedChat()).target_units(segment, "ta", rates)

    first = FittingTranslator(model=ScriptedChat([tamil_of(target - 3)]), cache=cache)
    first.translate(segment, target_language="ta", model=rates)

    original = prompts.PROMPT_VERSION
    try:
        prompts.PROMPT_VERSION = original + 1
        import importlib

        from app.translate import fitting

        importlib.reload(fitting)
        second = fitting.FittingTranslator(
            model=ScriptedChat([tamil_of(target - 3)]), cache=cache
        )
        second.translate(segment, target_language="ta", model=rates)
        assert len(second.model.calls) == 1
    finally:
        prompts.PROMPT_VERSION = original
        import importlib

        from app.translate import fitting

        importlib.reload(fitting)


def test_terms_that_must_stay_in_english_reach_the_prompt():
    """The client's translation instructions: bold terms are transliterated,
    never translated. Step 0 captured them; this is where they are used."""
    prompt = build_first_request(
        "Open the terminal by pressing Ctrl + Alt + T keys together.",
        "ta",
        22,
        ["terminal", "Ctrl"],
    )
    assert "terminal" in prompt and "Ctrl" in prompt
    assert "22" in prompt


def test_model_wrappers_are_stripped_before_counting():
    """A stray code fence or a 'Translation:' label would be counted as
    narration and eat into the budget."""
    assert clean_reply("```\n" + WORD + "\n```") == WORD
    assert clean_reply("Translation: " + WORD) == WORD
    assert clean_reply('"' + WORD + '"') == WORD


def test_groq_without_a_key_fails_with_a_usable_message():
    model = GroqChat(api_key="")
    if model.available:
        return  # a real key is configured on this machine
    try:
        model.complete("s", "u")
    except LLMError as error:
        assert "GROQ_API_KEY" in str(error)
    else:
        raise AssertionError("expected LLMError")


if __name__ == "__main__":
    failures = 0
    for name, function in sorted(globals().items()):
        if not name.startswith("test_") or not callable(function):
            continue
        try:
            function()
            print(f"  PASS  {name}")
        except AssertionError as error:
            failures += 1
            print(f"  FAIL  {name}: {error}")
    print()
    print("all passed" if not failures else f"{failures} failing")
    sys.exit(1 if failures else 0)
