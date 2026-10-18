"""Keep on-screen terms out of the machine translator's reach.

The learner matches the narration against the screen, so menu names, buttons,
keys, commands and product names must reach them exactly as displayed (the
client's translation rule; see prompts.py rule 3). IndicTrans2 does not know
that: unprotected, it renders "Synfig" as ஒத்திசைவின் ("of synchronisation"),
File and Save as கோப்பு and சேமி, and transliterates `sudo apt-get install`
into Tamil script.

So each term is swapped for an opaque placeholder before translation and put
back after. Measured on the client's script, IndicTrans2 carries `TERMX1`-style
tokens through and attaches Tamil case endings to them naturally ("TERMX1
இன்" - "of TERMX1"), which is exactly how a Spoken Tutorial writes "Synfig இன்".

Which occurrences to protect is the hard part, because bold marks a USE, not a
word. On the client's script:

  * "Enter" is bold in S-021 as the key ("press Enter"), and the same row's
    next sentence opens "Enter the system password" - the verb.
  * "Next" is bold once, as a button, and appears eleven more times as the
    ordinary word "next".
  * "Synfig" is bold at the start of sentences, legitimately.

Hence two rules:

  * a segment's OWN bold terms are protected as many times as they were
    bolded, mid-sentence occurrences first - the bold run is the button, the
    sentence-initial capital is grammar;
  * a term bold only ELSEWHERE in the script is protected here only if it is
    a name, not a word: anything multi-word or non-alphabetic, or a single
    word whose lower-case form never appears in the script ("Synfig" yes,
    "Next" and "Install" no).

Text that is never words - URLs, file names, versions, key combinations, shell
commands - is protected wherever it occurs.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

PLACEHOLDER = "TERMX{}"
TERMS_LOST = "on-screen term(s) lost"
"""How a translation that dropped a protected term is marked in its note."""
_PLACEHOLDER = re.compile(r"TERMX\s?(\d+)")
_TRANSLITERATED = re.compile(
    r"டி\.?\s*இ\.?\s*ஆர்\.?\s*எம்\.?\s*எக்ஸ்\s*(\d+)"
)
"""IndicTrans2 occasionally spells the placeholder out in Tamil letters -
"டி. இ. ஆர். எம். எக்ஸ்1" for TERMX1 (seen on S-049). Recognised on restore."""

TRAILING = ".,:;!?\"'()"

_PATTERNS = [
    re.compile(r"https?://\S+|www\.\S+"),
    re.compile(r"\b(?:Ctrl|Alt|Shift|Super|Cmd)(?:\s*\+\s*[A-Za-z0-9]+)+"),
    re.compile(r"\b(?:sudo|apt-get|apt|cd|ls|chmod|wget|pip)\b[\w ./=-]*[\w/]"),
    re.compile(r"\b[\w-]+\.(?:exe|png|jpe?g|gif|svg|sifz?|deb|sh|zip|tar\.gz|txt|py|html?)\b"),
    re.compile(r"\b\d+(?:\.\d+){1,3}\b"),
]


def clean_term(term: str) -> str:
    """Bold runs carry the punctuation that followed them ("Synfig.",
    "Enter."); the term is the text without it."""
    return term.strip().strip(TRAILING).strip()


def _is_word(term: str) -> bool:
    return term.isalpha() and " " not in term


def glossary(term_lists: Iterable[Iterable[str]], texts: Iterable[str] | None = None) -> list[str]:
    """The script's protectable names, longest first - so "Synfig Studio" is
    protected whole before "Synfig" could split it.

    With `texts` (every segment of the script), single words that also occur
    in lower case are dropped: they are ordinary words that happen to be bold
    somewhere, and protecting them in other segments keeps English in the
    middle of a Tamil sentence."""
    terms = {clean_term(t) for terms in term_lists for t in terms}
    terms = {t for t in terms if len(t) >= 2}
    if texts is not None:
        corpus = " ".join(texts)
        lower_words = set(re.findall(r"\b[a-z][a-z]+\b", corpus))
        terms = {
            t for t in terms
            if not (_is_word(t) and not t.islower() and t.lower() in lower_words)
        }
    return sorted(terms, key=lambda t: (-len(t), t))


def at_sentence_start(text: str, position: int) -> bool:
    before = text[:position].rstrip()
    return not before or before[-1] in ".!?:"


def protect(
    text: str, terms: Iterable[str], own: Iterable[str] = ()
) -> tuple[str, list[str]]:
    """Replace protected spans with numbered placeholders.

    `terms` are protected wherever they occur; `own` - this segment's bold
    runs, with repeats - only as many times as they were bolded. Returns the
    protected text and the originals: placeholder N is `originals[N - 1]`, and
    a recurring original reuses its number."""
    counts = Counter(c for c in (clean_term(t) for t in own) if len(c) >= 2)
    names = {c for c in (clean_term(t) for t in terms) if len(c) >= 2} - set(counts)

    spans: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in spans)

    for term in sorted(names | set(counts), key=lambda t: (-len(t), t)):
        pattern = re.compile(rf"(?<![\w]){re.escape(term)}(?![\w])")
        matches = [m for m in pattern.finditer(text) if free(m.start(), m.end())]
        if term in counts:
            matches.sort(key=lambda m: (at_sentence_start(text, m.start()), m.start()))
            matches = matches[: counts[term]]
        spans.extend((m.start(), m.end()) for m in matches)

    for pattern in _PATTERNS:
        spans.extend(
            (m.start(), m.end()) for m in pattern.finditer(text) if free(m.start(), m.end())
        )

    originals: list[str] = []
    index: dict[str, int] = {}
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        original = text[start:end]
        if original not in index:
            originals.append(original)
            index[original] = len(originals)
        pieces.append(text[cursor:start])
        pieces.append(PLACEHOLDER.format(index[original]))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), originals


def restore(text: str, originals: list[str]) -> str:
    """Put the originals back. A placeholder the model invented, or one whose
    number is out of range, is left visible rather than guessed at - the
    missing-term check then sends the segment to the LLM to repair."""

    def back(match: re.Match) -> str:
        digits = match.group(1)
        number = int(digits)
        if 1 <= number <= len(originals):
            return originals[number - 1]
        # A placeholder followed by a number in the source ("converted to
        # TERMX2 1") can come back glued: "TERMX21". If a prefix of the digits
        # is a real placeholder, the rest is the number that followed it.
        for cut in range(len(digits) - 1, 0, -1):
            head = int(digits[:cut])
            if 1 <= head <= len(originals):
                return f"{originals[head - 1]} {digits[cut:]}"
        return match.group(0)

    return _PLACEHOLDER.sub(back, _TRANSLITERATED.sub(back, text))


def has_placeholder(text: str) -> bool:
    """True if a placeholder survived restore - the line is not deliverable."""
    return bool(_PLACEHOLDER.search(text) or _TRANSLITERATED.search(text))


def fix_punctuation(source: str, output: str) -> str:
    """IndicTransToolkit's postprocessing turns a colon after a word into the
    Tamil aytham (ஃ) - "கற்றுக்கொள்வோம்ஃ" for "we will learn:". Inside a word ஃ
    is a real letter (எஃகு, "steel"), so only a word-final one is changed back,
    and only when the source had a colon to lose."""
    if ":" not in source:
        return output
    return re.sub(r"ஃ(?=\s|$)", ":", output)
