"""Any script, any language: OpenDocument scripts, every Indic script's
aksharas, and calibrating a voice the first time it is used."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.duration.calibrate import calibrated_rate, choose_lines  # noqa: E402
from app.duration.model import voice_key  # noqa: E402
from app.duration.syllables import count_syllables  # noqa: E402
from app.parsing.docx_reader import read_script, script_format  # noqa: E402
from app.parsing.parser import parse_rows, parse_script  # noqa: E402
from app.pipeline import runner  # noqa: E402
from app.pipeline.runner import PipelineConfig, Providers, _adapt, _map, ensure_voice_rate  # noqa: E402
from app.schemas import AlignmentResult, AudioAsset  # noqa: E402
from app.tts.silent import write_silence  # noqa: E402
from tests._paths import ENGLISH_SCRIPT  # noqa: E402

# -- OpenDocument scripts -----------------------------------------------------

CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
 <office:automatic-styles>
  <style:style style:name="T1" style:family="text"><style:text-properties fo:font-weight="bold"/></style:style>
  <style:style style:name="T2" style:family="text"><style:text-properties fo:font-style="italic"/></style:style>
 </office:automatic-styles>
 <office:body><office:text><table:table table:name="Table1">
  <table:table-row>
   <table:table-cell><text:p><text:span text:style-name="T1">Time</text:span></text:p></table:table-cell>
   <table:table-cell><text:p>Narration</text:p></table:table-cell>
  </table:table-row>
  <table:table-row>
   <table:table-cell><text:p>00:01 </text:p></table:table-cell>
   <table:table-cell><text:p>Welcome to the <text:span text:style-name="T1">spoken tutorial</text:span> on <text:span text:style-name="T1">Tables.</text:span></text:p></table:table-cell>
  </table:table-row>
  <table:table-row>
   <table:table-cell><text:p>00:07</text:p></table:table-cell>
   <table:table-cell><text:p>Press<text:s text:c="2"/><text:span text:style-name="T1">Ctrl</text:span><text:span text:style-name="T1"> + B</text:span></text:p>
     <text:p>to make it <text:span text:style-name="T2">bold</text:span>.</text:p></table:table-cell>
  </table:table-row>
 </table:table></office:text></office:body>
</office:document-content>"""


def _odt(folder: str, name: str) -> str:
    path = os.path.join(folder, name)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr("content.xml", CONTENT)
    return path


def test_an_odt_script_reads_like_a_docx():
    with tempfile.TemporaryDirectory() as folder:
        rows = read_script(_odt(folder, "script.odt"))
    assert [r.time for r in rows] == ["00:01", "00:07"]  # header dropped
    assert rows[0].narration == "Welcome to the spoken tutorial on Tables."
    assert rows[0].bold_terms == ["spoken tutorial", "Tables."]
    assert rows[1].narration == "Press Ctrl + B to make it bold."
    assert "Ctrl" in rows[1].bold_terms and "bold" not in rows[1].bold_terms  # italics ignored


def test_the_format_is_sniffed_not_trusted_from_the_name():
    """Three of the client's LibreOffice scripts are .odt files named .docx."""
    with tempfile.TemporaryDirectory() as folder:
        renamed = _odt(folder, "Table and table properties.docx")
        assert script_format(renamed) == "odt"
        script = parse_script(renamed, language="en", duration=20.0)
    assert [s.start for s in script.segments] == [1.0, 7.0]
    assert script_format(ENGLISH_SCRIPT) == "docx"


# -- aksharas in every script ---------------------------------------------------


def test_every_indic_script_is_counted():
    words = {
        "తెలుగు భాష": 5,  # Telugu: te-lu-gu bhaa-sha
        "বাংলা ভাষা": 4,  # Bengali: baang-laa bhaa-shaa
        "മലയാളം": 4,  # Malayalam: ma-la-yaa-lam
        "ગુજરાતી": 4,  # Gujarati: gu-ja-raa-tee
        "ಕನ್ನಡ": 3,  # Kannada: ka-nna-da (virama joins the cluster)
        "ਪੰਜਾਬੀ": 3,  # Punjabi: pan-jaa-bee
        "ଓଡ଼ିଆ": 3,  # Odia: o-di-aa (nukta is not a syllable)
        "हिन्दी": 2,  # Hindi: hi-ndee
        "தமிழ்": 2,  # Tamil: ta-mizh
    }
    for text, expected in words.items():
        assert count_syllables(text) == expected, text


def test_mixed_script_lines_still_count_latin_terms():
    assert count_syllables("Writer खोलें") == count_syllables("Writer") + count_syllables("खोलें")


# -- calibrating a new voice ----------------------------------------------------


class _Voice:
    """Speaks every akshara in exactly 1/RATE seconds."""

    name = "fake-voice"
    supports_pace = True
    RATE = 4.0

    def __init__(self) -> None:
        self.pace = 1.0
        self.speaker = "asha"
        self.calls = 0

    def synthesize(self, translated, *, out_path, voice=None, pace=None):
        self.calls += 1
        seconds = translated.syllables / self.RATE
        write_silence(out_path, seconds)
        return AudioAsset(segment_id=translated.segment_id, language=translated.language,
                          path=out_path, duration=seconds, provider=self.name)


class _Aligner:
    name = "span"

    def align(self, audio, text):
        return AlignmentResult(segment_id=audio.segment_id, speech_start=0.0,
                               speech_end=audio.duration, aligner=self.name)


class _Drafter:
    name = "fake-mt"

    def __init__(self) -> None:
        self.prepared = 0

    def prepare(self, segments, target_language):
        self.prepared += 1

    def draft(self, segment, target_language):
        return "हिन्दी " * max(segment.syllables // 4, 1)


class _Translator:
    def __init__(self, drafter) -> None:
        self.drafter = drafter


def test_a_new_voice_is_measured_once_from_the_scripts_own_drafts():
    script = parse_script(ENGLISH_SCRIPT, language="en", duration=663.2)
    voice = _Voice()
    voice.pace = 0.8
    drafter = _Drafter()
    providers = Providers(translator=_Translator(drafter), tts=voice, aligner=_Aligner(), exporters=[])
    stages = []
    with tempfile.TemporaryDirectory() as out:
        rates = os.path.join(out, "rates.json")
        config = PipelineConfig(language="hi", out_dir=out)
        rate = ensure_voice_rate(script, config, providers, lambda s, d, t, i=None: stages.append(s), rates)

        assert abs(rate - _Voice.RATE) < 1e-6
        assert voice.calls == len(choose_lines(script.segments)) == 20
        key = voice_key("fake-voice", "asha", 0.8)
        assert calibrated_rate(key, "hi", rates) == rate
        assert abs(config.rate_model.rate("hi") - _Voice.RATE) < 1e-3
        assert "calibrate" in stages

        # Known now: a second track neither re-measures nor re-pays.
        again = ensure_voice_rate(script, PipelineConfig(language="hi", out_dir=out), providers,
                                  lambda *a: None, rates)
        assert again == rate and voice.calls == 20

        with open(rates, encoding="utf-8") as handle:
            assert list(json.load(handle)) == [key]


def test_stubs_are_never_calibrated():
    script = parse_script(ENGLISH_SCRIPT, language="en", duration=663.2)
    providers = runner.build_providers(PipelineConfig(language="hi"), script)
    with tempfile.TemporaryDirectory() as out:
        assert ensure_voice_rate(script, PipelineConfig(language="hi"), providers,
                                 rates_path=os.path.join(out, "r.json")) is None


# -- the live feed ------------------------------------------------------------


def test_progress_hooks_receive_items_only_if_they_ask():
    seen3, seen4 = [], []
    three = _adapt(lambda stage, done, total: seen3.append((stage, done, total)))
    four = _adapt(lambda stage, done, total, item=None: seen4.append(item))
    assert _map(lambda x: x * 2, [1, 2, 3], "s", three, 2) == [2, 4, 6]
    assert _map(lambda x: x * 2, [1, 2, 3], "s", four, 2) == [2, 4, 6]
    assert seen3 == [("s", 1, 3), ("s", 2, 3), ("s", 3, 3)]
    assert seen4 == [2, 4, 6]


def test_parse_rows_is_unchanged_for_untimed_continuations():
    from app.parsing.docx_reader import RawRow

    script = parse_rows([RawRow("00:01", "One."), RawRow("", "More."), RawRow("00:05", "Two.")],
                        source="x", language="en", duration=9.0)
    assert [s.text for s in script.segments] == ["One. More.", "Two."]


# -- found by the five-tutorial run ---------------------------------------------


def test_a_placeholder_glued_to_a_following_number_is_restored():
    """Typing S-044: "converted to TERMX2 1" came back from IndicTrans2 as
    "TERMX21" and was spoken as the placeholder."""
    from app.translate.terms import has_placeholder, restore

    restored = restore("bullet சின்னம் TERMX21 ஆக", ["bullet", "number"])
    assert restored == "bullet சின்னம் number 1 ஆக"
    assert not has_placeholder(restored)
    assert has_placeholder(restore("TERMX9 இல்", ["only"]))  # invented: left visible


def test_a_draft_with_a_surviving_placeholder_is_never_accepted():
    from app.schemas import Segment
    from app.translate.fitting import FittingTranslator
    from app.translate.llm import ScriptedChat
    from app.duration.model import RateModel

    class Drafter:
        name = "leaky-mt"

        def draft(self, segment, target_language):
            return "சின்னம் TERMX9 ஆக மாறுகிறது."

    chat = ScriptedChat(["சின்னம் எண் 1 ஆக மாறுகிறது."])
    translator = FittingTranslator(model=chat, drafter=Drafter())
    text = "The symbol becomes number 1."
    segment = Segment(id="S-1", index=0, start=0, end=10, raw_budget=10, cue_reserved=0,
                      narration_budget=10, text=text, char_count=len(text), syllables=8)
    result = translator.translate(segment, target_language="ta", model=RateModel.for_voice(None))
    assert "TERMX" not in result.text and result.stage == "shortened"


def test_calibrated_voices_count_english_terms_and_digits_at_their_spoken_length():
    from app.duration.model import RateModel
    from app.duration.syllables import DIGIT_WEIGHT, LATIN_WEIGHT, spoken_units

    assert spoken_units("தமிழ்") == 2
    assert spoken_units("Writer") == LATIN_WEIGHT * count_syllables("Writer")
    assert spoken_units("Windows 8", "ta") == LATIN_WEIGHT * 2 + DIGIT_WEIGHT
    assert spoken_units("Windows 8", "en") == 2  # English lines are not reweighted
    # The narrator's model - and the Step 1 analysis on it - keep plain counts.
    assert RateModel().units("Windows 8", "ta") == 2
    assert RateModel.for_voice(None).units("Windows 8", "ta") == spoken_units("Windows 8")


def test_only_real_problems_need_review():
    """Notes that only explain a line ("predicted over, but the audio fits")
    must not inflate the review count shown to the client."""
    from app.schemas import SegmentQA, TranslatedSegment
    from app.timeline.qa import needs_review
    from app.translate.terms import TERMS_LOST

    def line(fitted=True, note=None):
        return TranslatedSegment(segment_id="S-1", language="hi", source_text="x", text="y",
                                 fitted=fitted, note=note)

    def qa(within):
        return SegmentQA(segment_id="S-1", budget=2, predicted=2, actual=2, drift=0,
                         rate_ratio=1, within_drift=within)

    assert not needs_review(line(note="predicted +0.30s over, but the audio fits (-0.10s)"), qa(True))
    assert needs_review(line(fitted=False), qa(True))
    assert needs_review(line(), qa(False))
    assert needs_review(line(note=f"{TERMS_LOST}: document"), qa(True))
    assert not needs_review(line(), None)
