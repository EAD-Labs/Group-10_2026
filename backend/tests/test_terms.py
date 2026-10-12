"""Tests for on-screen term protection around machine translation."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.translate.prompts import missing_terms  # noqa: E402
from app.translate.terms import fix_punctuation, glossary, protect, restore  # noqa: E402


def test_bold_terms_become_placeholders_and_come_back():
    text, originals = protect("Click on the File menu and select Save.", ["File", "Save."])
    assert text == "Click on the TERMX1 menu and select TERMX2."
    # What IndicTrans2 actually returns for that line, case endings attached:
    tamil = "TERMX1 மெனுவைக் கிளிக் செய்து TERMX2 ஐத் தேர்ந்தெடுக்கவும்."
    assert restore(tamil, originals) == "File மெனுவைக் கிளிக் செய்து Save ஐத் தேர்ந்தெடுக்கவும்."


def test_a_recurring_term_reuses_its_placeholder():
    text, originals = protect("Synfig is free. Download Synfig now.", ["Synfig"])
    assert text == "TERMX1 is free. Download TERMX1 now."
    assert originals == ["Synfig"]


def test_terms_match_whole_words_only():
    text, _ = protect("Synfigstudio is the package; Synfig is the program.", ["Synfig"])
    assert "Synfigstudio" in text
    assert "TERMX1 is the program" in text


def test_longer_terms_are_protected_before_their_parts():
    terms = glossary([["Synfig"], ["Synfig Studio"]])
    assert terms == ["Synfig Studio", "Synfig"]
    text, originals = protect("Open Synfig Studio.", terms)
    assert text == "Open TERMX1." and originals == ["Synfig Studio"]


def test_commands_urls_files_versions_and_keys_are_protected_unasked():
    text, originals = protect(
        "Type sudo apt-get install synfigstudio, press Ctrl + S, save ball.png, "
        "visit https://synfig.org and use version 1.0.2.",
        [],
    )
    assert "sudo apt-get install synfigstudio" in originals
    assert "Ctrl + S" in originals
    assert "ball.png" in originals
    assert "https://synfig.org" in originals
    assert "1.0.2" in originals
    assert "sudo" not in text and "Ctrl" not in text


def test_an_unknown_placeholder_is_left_visible_not_guessed():
    assert restore("TERMX7 ஐத் திறக்கவும்", ["Synfig"]) == "TERMX7 ஐத் திறக்கவும்"


def test_the_colon_that_became_an_aytham_is_restored():
    source = "In this tutorial, we will learn about: Interface of Synfig"
    output = "நாம் கற்றுக்கொள்வோம்ஃ Synfig இன் இடைமுகம்"
    assert fix_punctuation(source, output) == "நாம் கற்றுக்கொள்வோம்: Synfig இன் இடைமுகம்"
    # Inside a word it is a real letter, and without a source colon it stays.
    assert fix_punctuation(source, "எஃகு") == "எஃகு"
    assert fix_punctuation("No colon here", "சொல்ஃ") == "சொல்ஃ"


def test_a_bold_runs_trailing_punctuation_does_not_count_as_missing():
    assert missing_terms("Synfig ஐத் திறக்கவும்", ["Synfig."]) == []
    assert missing_terms("ஒத்திசைவின் இடைமுகம்", ["Synfig."]) == ["Synfig"]


# -- which occurrences get protected (cases from the client's script) ---------


def test_an_own_bold_term_is_protected_as_often_as_it_was_bolded_mid_sentence_first():
    """S-021: "Enter" is bold once - the key. The next sentence opens with the
    verb "Enter", which must be translated."""
    text = "Type the command and press Enter. Enter the system password if required."
    protected, originals = protect(text, [], own=["Enter."])
    assert protected == "Type the command and press TERMX1. Enter the system password if required."
    assert originals == ["Enter"]


def test_a_bold_term_at_the_start_of_a_sentence_is_still_protected():
    """S-005 bolds "Synfig" as the first word; sentence position alone must
    not unprotect a name."""
    assert protect("Synfig version 1.0.2", [], own=["Synfig"])[0] == "TERMX1 version TERMX2"


def test_ordinary_words_bold_elsewhere_are_not_protected_here():
    """S-018: "Next" is a bold button in another segment, and appears in lower
    case throughout the script - an ordinary word, so translated here."""
    texts = [
        "Click on Next button.",
        "Next we will see how to install Synfig.",
        "In the next step, open Synfig.",
    ]
    names = glossary([["Next"], [], ["Synfig"]], texts)
    assert "Next" not in names and "Synfig" in names
    protected, _ = protect(texts[1], names)
    assert protected == "Next we will see how to install TERMX1."


def test_a_transliterated_placeholder_is_restored():
    """S-049, as IndicTrans2 actually produced it: TERMX spelled out in Tamil."""
    output = "டி. இ. ஆர். எம். எக்ஸ்1 அனிமேஷனை டி. இ. ஆர். எம். எக்ஸ்2 வடிவத்தில்"
    assert restore(output, ["Render", "avi"]) == "Render அனிமேஷனை avi வடிவத்தில்"
