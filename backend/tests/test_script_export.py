"""The dubbed script comes back in the client's own format: a Time |
Narration Word table that our own reader can parse again."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.export.script_docx import ScriptExporter, clock  # noqa: E402
from app.parsing.docx_reader import read_script  # noqa: E402
from app.parsing.parser import parse_script  # noqa: E402
from app.schemas import LanguageTrack, TranslatedSegment  # noqa: E402
from tests._paths import ENGLISH_SCRIPT  # noqa: E402


def test_clock_matches_the_scripts_time_column():
    assert clock(7) == "00:07"
    assert clock(663.2) == "11:03"
    assert clock(3725) == "1:02:05"


def test_the_dubbed_script_round_trips_through_our_own_reader():
    script = parse_script(ENGLISH_SCRIPT, language="en", duration=663.2)
    first = script.segments[0]
    term = first.bold_terms[0]
    translations = [
        TranslatedSegment(segment_id=s.id, language="ta", source_text=s.text,
                          text=f"{term} <மொழிபெயர்ப்பு> & {i}" if s is first else f"வரி {i}")
        for i, s in enumerate(script.segments)
    ]
    track = LanguageTrack(source=ENGLISH_SCRIPT, language="ta", duration=663.2, translations=translations)
    with tempfile.TemporaryDirectory() as out:
        [path] = ScriptExporter(script).export(track, out)
        assert path.endswith("ta-script.docx")
        rows = read_script(path)
    assert len(rows) == len(script.segments)
    assert rows[0].time == clock(first.start)
    assert rows[0].narration == f"{term} <மொழிபெயர்ப்பு> & 0"  # XML-escaped and back
    assert term.rstrip(".") in rows[0].bold_terms  # on-screen terms stay bold
    assert rows[-1].narration == f"வரி {len(script.segments) - 1}"
