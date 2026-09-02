"""Syllable counting for the duration model.

Characters are a poor proxy for spoken length across scripts: Tamil is an
abugida, so one akshara carries a whole consonant-vowel unit that Latin script
would spell with three or four characters.  Counting aksharas (Indic) and
vowel groups (Latin) puts the languages on a comparable footing.

Supported today: Tamil, Devanagari (Hindi/Marathi), Latin.  Indian-language
scripts routinely embed Latin-script technical terms, so every counter is
mixed-script by design.
"""

from __future__ import annotations

import re

TAMIL_VOWELS = (0x0B85, 0x0B94)
TAMIL_CONSONANTS = (0x0B95, 0x0BB9)
TAMIL_VIRAMA = "\u0BCD"

DEVANAGARI_VOWELS = (0x0905, 0x0914)
DEVANAGARI_CONSONANTS = (0x0915, 0x0939)
DEVANAGARI_VIRAMA = "\u094D"

_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'\-\.]*")
_VOWELS = "aeiouy"


def _indic_aksharas(text: str, vowels, consonants, virama: str) -> int:
    count = 0
    chars = list(text)
    for index, char in enumerate(chars):
        code = ord(char)
        if vowels[0] <= code <= vowels[1]:
            count += 1
        elif consonants[0] <= code <= consonants[1]:
            following = chars[index + 1] if index + 1 < len(chars) else ""
            # A consonant followed by virama is half - it joins the next akshara.
            if following != virama:
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
    total = _indic_aksharas(text, TAMIL_VOWELS, TAMIL_CONSONANTS, TAMIL_VIRAMA)
    total += _indic_aksharas(
        text, DEVANAGARI_VOWELS, DEVANAGARI_CONSONANTS, DEVANAGARI_VIRAMA
    )
    for word in _LATIN_WORD.findall(text):
        total += latin_word_syllables(word)
    return total
