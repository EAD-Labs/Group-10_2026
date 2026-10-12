"""Prompt construction for duration-constrained translation.

Two things are being asked of the model at once: translate faithfully, and land
inside a length budget. The budget is expressed in the unit we actually measure
(aksharas for Indic scripts, syllables for Latin) rather than in seconds,
because the model has no idea what speaking rate we assume - and a target it
cannot evaluate is a target it cannot hit.

The rules below are the client's own, from the Translation Instructions they
supplied and the Dubbers' Checklist, not invented house style.
"""

from __future__ import annotations

import re

PROMPT_VERSION = 2
"""Bumped whenever the wording below changes. It forms part of the cache key,
so an edit here correctly misses the cache instead of returning text that an
earlier instruction produced."""

LANGUAGE_NAMES = {"ta": "Tamil", "hi": "Hindi", "mr": "Marathi", "en": "English"}

UNIT_NAMES = {"ta": "aksharas", "hi": "aksharas", "mr": "aksharas", "en": "syllables"}

UNITS_PER_WORD = {"ta": 2.75, "hi": 2.6, "mr": 2.6, "en": 1.57}
"""Median units per word. Tamil (2.75) and English (1.57) are measured from the
client's Synfig scripts; Hindi and Marathi are estimates until a matched pair
arrives for them. Used only to give the model a rough word count alongside the
authoritative unit budget - models control word counts better than syllables."""


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def unit_name(code: str) -> str:
    return UNIT_NAMES.get(code, "syllables")


def approximate_words(units: float, code: str) -> int:
    return max(int(round(units / UNITS_PER_WORD.get(code, 2.5))), 1)


def build_system_prompt(target_language: str) -> str:
    language = language_name(target_language)
    return (
        f"You translate Spoken Tutorial narration from English into {language}.\n\n"
        + _context_and_rules(target_language)
    )


def build_editor_system_prompt(target_language: str) -> str:
    """For the edit path: a machine translation already exists and the job is
    to make it fit, not to translate from scratch.

    Starting from the draft rather than the English keeps the model's work to
    the part it is needed for - cutting - and keeps vocabulary the MT model
    chose well instead of re-rolling every word."""
    language = language_name(target_language)
    return (
        f"You edit machine-translated {language} narration for Spoken Tutorials "
        f"so that it fits a time budget. You are given the English original and "
        f"a {language} draft; correct the draft where it mistranslates, and make "
        f"it shorter where it is too long.\n\n"
        + _context_and_rules(target_language)
    )


def _context_and_rules(target_language: str) -> str:
    language = language_name(target_language)
    units = unit_name(target_language)
    return f"""A Spoken Tutorial is a step-by-step software lesson. The learner watches the \
screen and copies each action, so the narration is locked to what is happening \
in the video. The audience may be as young as Class V.

The video cannot be changed, so each line must be sayable in the time the \
original English line occupies. That is why every request carries a hard \
{units} budget. Fitting the budget matters as much as the translation itself.

Rules, from the client's own translation guidelines:
1. Preserve the meaning and the instruction. Never invent a step, never drop a step.
2. Use simple, precise, everyday words. No literary register, no jargon.
3. Anything the learner must find on screen stays in LATIN script, spelled \
exactly as in the English line: software names, menu items, button labels, key \
names, file names, URLs and commands. Synfig, Enter, Ctrl + Alt + T, Continue, \
Install, .exe all stay as they are. Do not rewrite them in {language} script \
and never translate them - the learner is matching your words against what is \
on the screen in front of them.
4. Ordinary computing vocabulary that has entered everyday {language} speech \
may be written in {language} script - words like tutorial, type, click, image. \
The test is whether the word names something visible on screen (keep it Latin) \
or is simply a word in the sentence (it may be transliterated).
5. Any term listed as "keep in Latin script" in the request must appear \
unchanged, in Latin script.
6. Prefer active voice and one instruction per sentence.
7. Two short source sentences may be merged into one if that saves length \
without losing a step.
8. Shorten by removing padding, filler and redundancy first. Only compress \
meaning when there is no other way to fit.

Output rules:
- Reply with the {language} translation ONLY.
- No preamble, no explanation, no quotation marks, no markdown, no notes \
about length.
- One line of output, unless the source genuinely contains two sentences."""


def build_first_request(
    source_text: str,
    target_language: str,
    target_units: int,
    bold_terms: list[str] | None = None,
) -> str:
    units = unit_name(target_language)
    words = approximate_words(target_units, target_language)
    keep = ""
    if bold_terms:
        keep = (
            "\nKeep in Latin script exactly as written: "
            + ", ".join(sorted(set(bold_terms)))
        )
    return f"""English line:
{source_text}
{keep}

Budget: at most {target_units} {units} (roughly {words} words or fewer).

Translate it into {language_name(target_language)} within that budget."""


def build_edit_request(
    source_text: str,
    target_language: str,
    target_units: int,
    draft: str,
    draft_units: int,
    bold_terms: list[str] | None = None,
    missing_terms: list[str] | None = None,
) -> str:
    """Ask for the draft to be brought inside the budget, and any on-screen
    term the MT model translated to be restored in Latin script."""
    units = unit_name(target_language)
    language = language_name(target_language)
    words = approximate_words(target_units, target_language)
    problems = []
    if draft_units > target_units:
        excess = draft_units - target_units
        percent = round(100 * excess / draft_units)
        problems.append(
            f"It uses {draft_units} {units}; the limit is {target_units}, so it must "
            f"lose at least {excess} {units} (about {percent}% shorter)."
        )
    if missing_terms:
        problems.append(
            "These on-screen terms are missing or were translated; they must appear "
            "exactly as written, in Latin script: " + ", ".join(missing_terms) + "."
        )
    keep = ""
    if bold_terms:
        keep = "\nKeep in Latin script exactly as written: " + ", ".join(sorted(set(bold_terms)))
    problem = " ".join(problems)
    return f"""English line:
{source_text}
{keep}

{language} draft:
{draft}

{problem}

Budget: at most {target_units} {units} (roughly {words} words or fewer).

Rewrite the draft to fix this. Drop filler and repetition first; merge \
clauses; use shorter everyday words. Keep every instruction the learner has to \
follow. Reply with the {language} text only."""


def missing_terms(text: str, terms: list[str] | None) -> list[str]:
    """On-screen terms that did not survive into `text` verbatim.

    Matched case-insensitively and whitespace-normalised, because the learner
    is matching words against a screen and "Ctrl+Alt+T" vs "Ctrl + Alt + T" is
    not a difference they will notice."""
    from .terms import clean_term

    if not terms:
        return []
    squash = lambda value: "".join(value.split()).casefold()  # noqa: E731
    haystack = squash(text)
    wanted = dict.fromkeys(clean_term(t) for t in terms)
    return [term for term in wanted if squash(term) and squash(term) not in haystack]


def build_retry_request(
    source_text: str,
    target_language: str,
    target_units: int,
    previous_attempt: str,
    previous_units: int,
    bold_terms: list[str] | None = None,
) -> str:
    units = unit_name(target_language)
    excess = previous_units - target_units
    percent = round(100 * excess / previous_units) if previous_units else 0
    keep = ""
    if bold_terms:
        keep = (
            "\nStill keep in Latin script exactly as written: "
            + ", ".join(sorted(set(bold_terms)))
        )
    return f"""That was too long.

Your translation:
{previous_attempt}

It uses {previous_units} {units}. The limit is {target_units} {units}, so it \
must lose at least {excess} {units} (about {percent}% shorter).

English line it must still convey:
{source_text}
{keep}

Rewrite it shorter. Drop filler and repetition first; merge clauses; use \
shorter everyday words. Keep every instruction the learner has to follow. \
Reply with the {language_name(target_language)} translation only."""


_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_LABEL = re.compile(
    r"^\s*(?:translation|tamil|hindi|marathi|output|answer)\s*[:\-]\s*", re.IGNORECASE
)


def clean_reply(text: str) -> str:
    """Strip the wrappers models add even when told not to.

    Length is measured on this, so a stray code fence or a "Translation:" label
    would be counted as narration and skew the budget."""
    text = _FENCE.sub("", text.strip()).strip()
    text = _LABEL.sub("", text).strip()
    if len(text) >= 2 and text[0] in "\"'\u201c\u2018" and text[-1] in "\"'\u201d\u2019":
        text = text[1:-1].strip()
    return " ".join(text.split())
