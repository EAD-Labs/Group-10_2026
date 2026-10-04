"""Regression tests against the client's Synfig "Overview and Installation"
scripts - a matched English/Tamil pair over one identical 663.2s video.

These two files are ground truth for the whole duration model, so the numbers
here are asserted rather than merely printed.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.duration.model import RateModel, calibrate_from_script, fit_track  # noqa: E402
from app.parsing.cues import parse_cue  # noqa: E402
from app.parsing.docx_reader import RawRow  # noqa: E402
from app.parsing.parser import parse_rows, parse_script  # noqa: E402
from app.parsing.sentences import split_sentences  # noqa: E402

MATERIALS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
ENGLISH = os.path.join(MATERIALS, "Timed-script-sample-english.docx")
TAMIL = os.path.join(MATERIALS, "Tamil-script-sample.docx")

# Measured from the webm containers the client supplied.
VIDEO_DURATION = 663.2


def english():
    return parse_script(ENGLISH, language="en", duration=VIDEO_DURATION)


def tamil():
    return parse_script(TAMIL, language="ta", duration=VIDEO_DURATION)


def test_english_structure():
    script = english()
    assert len(script.segments) == 95
    assert len(script.cues) == 11


def test_tamil_structure():
    script = tamil()
    assert len(script.segments) == 95
    assert len(script.cues) == 11


def test_the_pair_is_segment_aligned():
    """Every Tamil row sits at the same timestamp as its English counterpart.
    This is what makes the pair usable for calibration."""
    for left, right in zip(english().segments, tamil().segments):
        assert left.start == right.start, f"{left.id}: {left.start} vs {right.start}"


def test_cue_rows_are_not_counted_as_narration():
    script = english()
    assert all(segment.text.lstrip()[0] != "@" for segment in script.segments)
    assert script.cues[0].at == 4 * 60 + 56
    assert script.cues[0].clip_start == 5 * 60 + 44
    assert script.cues[0].clip_end == 5 * 60 + 51
    assert script.cues[0].clip_duration == 7.0


def test_tamil_cues_parse_despite_reversed_word_order():
    """The Tamil script writes the clip range before the verb, so cue parsing
    cannot depend on the English 'from X to Y' wording."""
    cues = tamil().cues
    assert len(cues) == 11
    assert all(cue.clip_duration > 0 for cue in cues)
    assert cues[0].at == 4 * 60 + 56


def test_embedded_clips_do_not_count_as_narration_time():
    """The trap this parser exists to avoid: a row in front of an embedded clip
    looks generous but nearly all of its window is already occupied."""
    script = english()
    with_cues = [s for s in script.segments if s.cue_ids]
    assert len(with_cues) == 11
    for segment in with_cues:
        assert segment.narration_budget < segment.raw_budget

    assert round(sum(s.cue_reserved for s in script.segments), 1) == 90.0
    # Only this much of the apparent slack is genuinely free for holds.
    assert round(sum(s.trailing_slack for s in script.segments), 1) == 11.0


def test_delivered_pace_english_is_the_reference():
    assert round(calibrate_from_script(english()), 2) == 3.00


def test_tamil_was_delivered_rushed():
    """The client's complaint, measured: the Tamil dub runs a third faster than
    the English it has to fit inside."""
    english_pace = calibrate_from_script(english())
    tamil_pace = calibrate_from_script(tamil())
    assert round(tamil_pace, 2) == 4.00
    assert tamil_pace / english_pace > 1.30


def test_tamil_does_not_fit_at_a_natural_pace():
    """Spoken at the English articulation rate the Tamil text needs more time
    than the video gives it. This is the gap the fitting engine must close.

    Budget here is the speaking budget - the window minus the reserved pause -
    so these numbers are what a translation must actually hit."""
    script = tamil()
    fit = fit_track(script, None, "ta", RateModel())

    assert round(fit.total_predicted) == 591
    assert round(fit.total_budget, 1) == 523.2
    assert 1.10 < fit.total_predicted / fit.total_budget < 1.20
    assert len(fit.over_budget) == 63


def test_english_script_is_not_flagged_as_broken():
    """Regression guard on false alarms.

    The English script was recorded and delivered at exactly these timings, so
    a model that flags a large share of it is wrong about the model, not the
    script. The Step 0 model flagged 42 of 95; measuring real articulation and
    reserving the pause brought that down to 11."""
    fit = fit_track(english(), None, "en", RateModel())
    assert len(fit.over_budget) <= 15
    assert fit.total_predicted < fit.total_budget


def test_a_reversed_clip_range_still_reserves_the_right_time():
    """A cue written end-first must not silently reserve zero seconds.

    The old code swapped the two stamps and then subtracted them in the
    pre-swap order, so the difference came out negative and fell through to
    0.0. A cue reserving 0 s leaves the segment's budget too generous and the
    narration lands on top of the embedded clip - wrong, with no error."""
    reversed_cue = parse_cue("@04:56 Add the audio of X from 05:51 to 05:44", 1)
    forward_cue = parse_cue("@04:56 Add the audio of X from 05:44 to 05:51", 1)

    assert reversed_cue.clip_duration == 7.0
    assert reversed_cue.clip_duration == forward_cue.clip_duration
    assert reversed_cue.clip_start == forward_cue.clip_start
    assert reversed_cue.clip_end == forward_cue.clip_end
    assert reversed_cue.reversed_range is True
    assert forward_cue.reversed_range is False


def test_a_reversed_range_is_corrected_but_not_hidden():
    """The order is fixed so the arithmetic is right; the author is still told,
    because one of the two files has a typo and only they can say which."""
    rows = [
        RawRow(time="00:10", narration="Here is a glimpse of the tutorial."),
        RawRow(time="", narration="@00:12 Add the audio of X from 00:25 to 00:18"),
        RawRow(time="00:30", narration="The next tutorial."),
    ]
    script = parse_rows(rows, source="typo.docx", language="en", duration=40.0)

    cue = script.cues[0]
    assert cue.clip_duration == 7.0

    segment = script.segments[0]
    assert segment.cue_reserved == 7.0
    # 00:12 anchor minus the 00:10 start: the clip owns everything after it.
    assert segment.narration_budget == 2.0

    warnings = [v for v in segment.violations if v.rule == "ST-CUE-ORDER"]
    assert len(warnings) == 1
    assert warnings[0].severity == "warning"
    assert "00:18" in warnings[0].message and "00:25" in warnings[0].message


def test_an_equal_clip_range_is_zero_not_reversed():
    cue = parse_cue("@04:56 Add the audio of X from 05:44 to 05:44", 1)
    assert cue.clip_duration == 0.0
    assert cue.reversed_range is False


def test_the_real_scripts_have_no_reversed_ranges():
    """Both client files are forward-ordered today. If a future script is not,
    this fails and the warning path above is what reports it."""
    assert all(not cue.reversed_range for cue in english().cues)
    assert all(not cue.reversed_range for cue in tamil().cues)


def test_sentence_rules_apply_to_sentences_not_rows():
    """21 English rows exceed 80 characters, but a row is an activity that may
    hold several sentences; only 12 actual sentences genuinely break the rule.
    Validating rows instead of sentences would nearly double the false alarms."""
    script = english()
    long_rows = [s for s in script.segments if s.char_count > 80]
    assert len(long_rows) == 21

    errors = [v for s in script.segments for v in s.violations if v.severity == "error"]
    assert len(errors) == 12
    assert all(v.rule == "ST-2.3.2" for v in errors)


def test_splitter_protects_urls_and_versions():
    assert split_sentences(
        "In the address bar, type the url: https://www.synfig.org/download-stable Press Enter."
    ) == [
        "In the address bar, type the url: https://www.synfig.org/download-stable Press Enter."
    ]
    assert len(split_sentences("Synfig version 1.0.2")) == 1
    assert len(split_sentences("Go to Downloads folder and double click on .exe file.")) == 1
    assert len(split_sentences(
        "Synfig is a 2D animation software. It is a free open source software."
    )) == 2


def test_bold_terms_are_captured_for_the_translator():
    """Bold terms must never be translated, only transliterated - so the parser
    has to carry them through to the translation stage."""
    script = english()
    assert any(segment.bold_terms for segment in script.segments)


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
