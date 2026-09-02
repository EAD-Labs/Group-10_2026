"""Pedagogy-rule validation.

Every rule id traces to a numbered item in the client's Dubbers' Checklist so a
flagged segment can be justified to the author.
"""

from __future__ import annotations

import re

from ..schemas import Segment, Sentence, Violation

SENTENCE_PREFERRED = 60   # checklist 2.3.1 - "most sentences less than 60 characters"
SENTENCE_MAX = 80         # checklist 2.3.2 - "all sentences less than 80 characters"

_VAGUE = re.compile(
    r"\b(?:go here|click here|click this|click that|over here|like this|"
    r"do this here|this one)\b",
    re.IGNORECASE,
)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+[,.;:!?]")


def validate_sentence(sentence: Sentence) -> list[Violation]:
    found: list[Violation] = []

    if sentence.char_count > SENTENCE_MAX:
        found.append(
            Violation(
                rule="ST-2.3.2",
                severity="error",
                message=(
                    f"Sentence is {sentence.char_count} characters; the limit is "
                    f"{SENTENCE_MAX}. Long sentences are difficult to translate."
                ),
                sentence_index=sentence.index,
            )
        )
    elif sentence.char_count > SENTENCE_PREFERRED:
        found.append(
            Violation(
                rule="ST-2.3.1",
                severity="warning",
                message=(
                    f"Sentence is {sentence.char_count} characters; prefer under "
                    f"{SENTENCE_PREFERRED} so it translates within the available time."
                ),
                sentence_index=sentence.index,
            )
        )

    vague = _VAGUE.search(sentence.text)
    if vague:
        found.append(
            Violation(
                rule="ST-2.1.1",
                severity="warning",
                message=f"Vague reference {vague.group(0)!r}; state the location explicitly.",
                sentence_index=sentence.index,
            )
        )

    if _SPACE_BEFORE_PUNCT.search(sentence.text):
        found.append(
            Violation(
                rule="ST-3.8.4",
                severity="warning",
                message="Space before a punctuation mark.",
                sentence_index=sentence.index,
            )
        )

    return found


def validate_segment(segment: Segment) -> list[Violation]:
    found: list[Violation] = []

    if not segment.text.strip():
        found.append(
            Violation(rule="ST-EMPTY", severity="error", message="Narration cell is empty.")
        )

    for sentence in segment.sentences:
        sentence.violations = validate_sentence(sentence)
        found.extend(sentence.violations)

    if segment.narration_budget <= 0:
        found.append(
            Violation(
                rule="ST-BUDGET",
                severity="error",
                message=(
                    "No time available for narration: the window is fully consumed "
                    "by an embedded clip."
                ),
            )
        )

    return found
