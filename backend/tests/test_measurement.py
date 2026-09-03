"""Tests for the audio measurement stage (Step 1).

These need the client's Synfig videos, which are not in the repository. When
they are absent every test reports SKIP rather than failing, so a teammate can
clone and run the suite without the media.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.duration.measure import calibrate, measure_script  # noqa: E402
from app.media.audio import extract_audio  # noqa: E402
from app.media.vad import detect_speech  # noqa: E402
from app.parsing.parser import parse_script  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(ROOT, "work", "audio")
VIDEO_DURATION = 663.2

TRACKS = {
    "en": (
        os.path.join(ROOT, "Overview-of-Synfig-English.webm"),
        os.path.join(ROOT, "Timed-script-sample-english.docx"),
    ),
    "ta": (
        os.path.join(ROOT, "Overview-of-Synfig-Tamil.webm"),
        os.path.join(ROOT, "Tamil-script-sample.docx"),
    ),
}


class Skip(Exception):
    """Raised when the client media is not available on this machine."""


def _load(language: str):
    video, script_path = TRACKS[language]
    if not os.path.exists(video):
        raise Skip(f"{os.path.basename(video)} not present")
    wav = extract_audio(video, os.path.join(WORK, f"synfig-{language}.wav"))
    script = parse_script(script_path, language=language, duration=VIDEO_DURATION)
    return script, detect_speech(wav)


def test_extracted_audio_matches_the_video_length():
    _, track = _load("en")
    assert abs(track.duration - VIDEO_DURATION) < 0.5


def test_english_narrator_does_not_talk_through_the_whole_window():
    """The premise of Step 1: a segment's window is speech plus a pause, so
    budgeting the whole window hands the translator time that is not there."""
    script, track = _load("en")
    result = calibrate(script, track)
    assert 0.65 < result.speech_fraction < 0.80
    assert result.pause_median > 0.25


def test_tamil_was_delivered_faster_and_without_pauses():
    """The client's complaint, measured from the audio rather than inferred
    from the script table."""
    english_result = calibrate(*_load("en"))
    tamil_result = calibrate(*_load("ta"))

    assert tamil_result.aggregate_rate / english_result.aggregate_rate > 1.20
    assert tamil_result.pause_median == 0.0
    assert tamil_result.segments_without_pause > english_result.segments_without_pause * 1.8


def test_embedded_clip_windows_are_excluded():
    """Those windows hold another tutorial's narration; measuring them would
    credit this script's syllables with someone else's speech."""
    script, track = _load("en")
    assert calibrate(script, track).segments_measured == 84
    assert len(measure_script(script, track, skip_cue_windows=False)) == 95


def test_speech_and_silence_partition_every_window():
    script, track = _load("en")
    for m in measure_script(script, track):
        assert 0 <= m.speech <= m.window + 1e-6
        assert m.trailing_pause + m.leading_silence <= m.window + 1e-6


if __name__ == "__main__":
    failures = skipped = 0
    for name, function in sorted(globals().items()):
        if not name.startswith("test_") or not callable(function):
            continue
        try:
            function()
            print(f"  PASS  {name}")
        except Skip as reason:
            skipped += 1
            print(f"  SKIP  {name}: {reason}")
        except AssertionError as error:
            failures += 1
            print(f"  FAIL  {name}: {error}")
    print()
    print(f"{failures} failing, {skipped} skipped" if failures or skipped else "all passed")
    sys.exit(1 if failures else 0)
