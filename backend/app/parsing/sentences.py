"""Sentence splitting for pedagogy-rule validation.

The 60/80-character rules in the Dubbers' Checklist (2.3.1, 2.3.2) apply to
*sentences*, but a timed-script row is an *activity* and routinely holds several
sentences.  So budgets attach to rows and validation runs over the sentences
inside them.

Naive splitting on "." destroys URLs, emails, version numbers and file
extensions, all of which occur in these scripts, so those are masked first.
"""

from __future__ import annotations

import re

_PROTECTED = [
    re.compile(r"https?://\S+"),
    re.compile(r"\bwww\.\S+"),
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+"),
    re.compile(r"\b\d+(?:\.\d+)+\b"),
    re.compile(r"(?<![A-Za-z0-9])\.[A-Za-z]{2,4}\b"),
    re.compile(r"\b(?:e\.g|i\.e|etc|Mr|Mrs|Ms|Dr|vs|No|Fig)\.", re.IGNORECASE),
]

_SPLIT = re.compile(r"(?<=[.!?\u0964])[\s\u200b]+")
_SENTINEL = "\x00%d\x00"


def _mask(text: str) -> tuple[str, list[str]]:
    stash: list[str] = []

    def swap(match: re.Match[str]) -> str:
        stash.append(match.group(0))
        return _SENTINEL % (len(stash) - 1)

    for pattern in _PROTECTED:
        text = pattern.sub(swap, text)
    return text, stash


def _unmask(text: str, stash: list[str]) -> str:
    for index, original in enumerate(stash):
        text = text.replace(_SENTINEL % index, original)
    return text


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []

    masked, stash = _mask(text)
    pieces = [_unmask(p, stash).strip() for p in _SPLIT.split(masked)]
    return [p for p in pieces if p]
