"""Tests for container probing, against the client's Synfig videos.

The .webm files are deliberately not in the repository - they are large and
not ours to redistribute (see .gitignore) - so every test here skips when they
are absent rather than failing. A teammate without the media, or CI, should
see skips; a teammate with it should see the client's claim checked.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.media.probe import probe, probe_duration  # noqa: E402

MATERIALS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGLISH_VIDEO = os.path.join(MATERIALS, "Overview-of-Synfig-English.webm")
TAMIL_VIDEO = os.path.join(MATERIALS, "Overview-of-Synfig-Tamil.webm")

# The figure hard-coded across the test suite before the probe existed.
ASSUMED_DURATION = 663.2


class Skipped(Exception):
    """Raised when the client media is not on this machine."""


def _require(path: str) -> str:
    if not os.path.exists(path):
        raise Skipped(f"{os.path.basename(path)} not present")
    return path


def test_probe_reads_the_english_video():
    info = probe(_require(ENGLISH_VIDEO))
    assert 663.0 < info.duration < 663.5, info.duration
    assert info.timecode_scale == 1_000_000
    assert info.muxer  # Matroska always records a writing application


def test_the_assumed_duration_was_correct():
    """663.2 was typed into every command and asserted in test_parser without
    anything ever checking it. It is right - now demonstrably."""
    duration = probe_duration(_require(ENGLISH_VIDEO))
    assert round(duration, 1) == ASSUMED_DURATION, duration


def test_both_language_videos_are_the_same_length():
    """The client's central claim: the visual track is authored once in English
    and reused, with only the audio replaced. If these two ever diverged, the
    per-segment budgets could not be shared between the tracks."""
    english = probe_duration(_require(ENGLISH_VIDEO))
    tamil = probe_duration(_require(TAMIL_VIDEO))
    assert abs(english - tamil) < 0.5, (english, tamil)


def test_every_action_cue_lands_inside_the_video():
    """A cue anchored past the end of the base video would mean the parser had
    misread a timestamp - the sort of error that is invisible until an editor
    opens the export."""
    from app.parsing.parser import parse_script

    duration = probe_duration(_require(ENGLISH_VIDEO))
    script = parse_script(
        os.path.join(MATERIALS, "Timed-script-sample-english.docx"),
        language="en",
        duration=duration,
    )
    assert script.cues
    for cue in script.cues:
        assert 0 <= cue.at <= duration, f"{cue.id} anchored at {cue.at}s"
    for segment in script.segments:
        assert segment.start <= duration, f"{segment.id} starts at {segment.start}s"


def test_a_missing_file_is_an_error_not_a_guess():
    try:
        probe(os.path.join(MATERIALS, "no-such-video.webm"))
    except ValueError as error:
        assert "no such file" in str(error)
    else:
        raise AssertionError("a missing video must not resolve to a duration")


def test_a_non_matroska_file_is_rejected():
    """Guessing a duration would put a wrong number under every budget."""
    try:
        probe(os.path.join(MATERIALS, "Timed-script-sample-english.docx"))
    except ValueError as error:
        assert "duration" in str(error)
    else:
        raise AssertionError("a .docx must not probe as a video")


if __name__ == "__main__":
    failures = skips = 0
    for name, function in sorted(globals().items()):
        if not name.startswith("test_") or not callable(function):
            continue
        try:
            function()
            print(f"  PASS  {name}")
        except Skipped as reason:
            skips += 1
            print(f"  SKIP  {name}: {reason}")
        except AssertionError as error:
            failures += 1
            print(f"  FAIL  {name}: {error}")
    print()
    summary = "all passed" if not failures else f"{failures} failing"
    print(f"{summary}{f', {skips} skipped (client media absent)' if skips else ''}")
    sys.exit(1 if failures else 0)
