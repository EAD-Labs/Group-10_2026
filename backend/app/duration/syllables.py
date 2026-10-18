"""Syllable counting for the duration model.

Characters are a poor proxy for spoken length across scripts: Tamil is an
abugida, so one akshara carries a whole consonant-vowel unit that Latin script
would spell with three or four characters.  Counting aksharas (Indic) and
vowel groups (Latin) puts the languages on a comparable footing.

Supported: every Brahmic script Sarvam and IndicTrans2 cover (see
INDIC_BLOCKS), and Latin.  Indian-language
scripts routinely embed Latin-script technical terms, so every counter is
mixed-script by design.
"""

from __future__ import annotations

import re

INDIC_BLOCKS = {
    0x0900: "Devanagari",  # Hindi, Marathi
    0x0980: "Bengali",
    0x0A00: "Gurmukhi",  # Punjabi
    0x0A80: "Gujarati",
    0x0B00: "Odia",
    0x0B80: "Tamil",
    0x0C00: "Telugu",
    0x0C80: "Kannada",
    0x0D00: "Malayalam",
}
"""The nine Brahmic script blocks. Unicode lays them out alike (ISCII-derived),
so one rule counts them all: independent vowels at offsets 05-14, consonants
at 15-39 (plus the precomposed nukta forms at 58-5F), virama at 4D."""

VIRAMA_OFFSET = 0x4D

# Kept for readers of the old per-script constants.
TAMIL_VOWELS = (0x0B85, 0x0B94)
TAMIL_CONSONANTS = (0x0B95, 0x0BB9)
TAMIL_VIRAMA = "்"

_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'\-\.]*")
_VOWELS = "aeiouy"


def _akshara_kind(char: str) -> tuple[int, str] | None:
    """(block base, 'vowel' | 'consonant' | 'virama') for an Indic letter."""
    code = ord(char)
    if not 0x0900 <= code < 0x0D80:
        return None
    base = code & ~0x7F
    offset = code - base
    if 0x05 <= offset <= 0x14 or offset in (0x60, 0x61):
        return base, "vowel"
    if 0x15 <= offset <= 0x39 or 0x58 <= offset <= 0x5F:
        return base, "consonant"
    if offset == VIRAMA_OFFSET:
        return base, "virama"
    return None


def _indic_aksharas(text: str) -> int:
    """Aksharas in every Indic script at once.

    A consonant followed by virama is half - it joins the next akshara."""
    count = 0
    for index, char in enumerate(text):
        kind = _akshara_kind(char)
        if kind is None or kind[1] == "virama":
            continue
        if kind[1] == "vowel":
            count += 1
            continue
        following = text[index + 1] if index + 1 < len(text) else ""
        if following != chr(kind[0] + VIRAMA_OFFSET):
            count += 1
    return count


def latin_word_syllables(word: str) -> int:
    word = word.lower()
    if not re.search(r"[a-z]", word):
        return 0

    count = 0
    previous_was_vowel = False
    for char in word:
        is_vowel = char in _VOWELS
        if is_vowel and not previous_was_vowel:
            count += 1
        previous_was_vowel = is_vowel

    if word.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def count_syllables(text: str) -> int:
    """Count syllables in mixed Indic/Latin text.

    Known limitation: bare numerals ("16.04", "0") are not counted, because how
    they are spoken is language-specific. Add a spoken-form expansion before
    this call once the client confirms the convention.
    """
    total = _indic_aksharas(text)
    for word in _LATIN_WORD.findall(text):
        total += latin_word_syllables(word)
    return total


LATIN_WEIGHT = 1.4
"""How long a Latin-script syllable takes, in aksharas, inside an Indic line.

Measured, not assumed: a least-squares fit of clip span against (aksharas,
Latin syllables, digits) over all 716 clips of five LibreOffice tutorials
dubbed in Tamil at pace 0.9 gave 0.168 s per akshara and 0.234 s per Latin
syllable - the voice slows down for on-screen English terms ("Bullets and
Numbering", "Free Sans"). Counting them at face value under-predicted exactly
the lines that overran; the fit cut the residual from 0.71 s to 0.55 s."""

DIGIT_WEIGHT = 2.6
"""Aksharas per digit (same fit: 0.443 s per digit). `count_syllables` counts
numerals as nothing - "Windows 8" and "version 6.3.5" are spoken in full."""

_DIGIT = re.compile(r"\d")


def spoken_units(text: str, language: str | None = None) -> float:
    """What the duration model budgets: aksharas, with Latin syllables and
    digits weighted by how long the voice actually takes over them.

    `count_syllables` stays the plain count (what a person would count, and
    what the English source's syllables are); this is the predictor. In an
    English line Latin syllables ARE the unit, so nothing is weighted."""
    if language == "en":
        return float(count_syllables(text))
    latin = sum(latin_word_syllables(w) for w in _LATIN_WORD.findall(text))
    indic = _indic_aksharas(text)
    return indic + LATIN_WEIGHT * latin + DIGIT_WEIGHT * len(_DIGIT.findall(text))
