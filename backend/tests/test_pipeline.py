"""Tests for the stubbed end-to-end pipeline.

The point of Step 2 is that the chain runs and the seams hold, so these tests
check plumbing and arithmetic, not narration quality - there is no narration
yet. Two things they pin down that will matter when the stubs are replaced:

  * the stub numbers agree with Module 1's own analysis (42 English segments
    over budget, 83 Tamil), so a future translator's improvement is measured
    against a baseline that is known to be right
  * a provider swap changes only what is written, never the shape of the track
"""

from __future__ import annotations

import os
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parsing.parser import parse_script  # noqa: E402
from app.pipeline.interfaces import Aligner, Exporter, TTSProvider, Translator  # noqa: E402
from app.pipeline.registry import (  # noqa: E402
    get_aligner,
    get_exporters,
    get_translator,
    get_tts,
)
from app.pipeline.runner import (  # noqa: E402
    PipelineConfig,
    run_pipeline,
    run_segments,
    run_track,
)
from app.schemas import QAReport, SegmentQA, TranslatedSegment  # noqa: E402

MATERIALS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGLISH = os.path.join(MATERIALS, "Timed-script-sample-english.docx")
TAMIL = os.path.join(MATERIALS, "Tamil-script-sample.docx")
VIDEO_DURATION = 663.2


def _run(script_path=ENGLISH, language="en", out_dir=None, **kwargs):
    config = PipelineConfig(language=language, out_dir=out_dir, **kwargs)
    return run_pipeline(script_path, config, duration=VIDEO_DURATION)


def test_stubs_satisfy_the_interfaces():
    """The Protocols are the team's contract; a stub that drifts out of shape
    breaks everyone silently."""
    assert isinstance(get_translator("echo"), Translator)
    assert isinstance(get_tts("silent"), TTSProvider)
    assert isinstance(get_aligner("clip-bounds"), Aligner)
    assert all(isinstance(e, Exporter) for e in get_exporters(["srt", "manifest"]))


def test_registry_rejects_an_unknown_provider():
    try:
        get_tts("sarvam")
    except ValueError as error:
        assert "available" in str(error)
    else:
        raise AssertionError("unknown provider should not resolve")


def test_pipeline_runs_end_to_end():
    with tempfile.TemporaryDirectory() as out:
        script, track = _run(out_dir=out)
        assert len(script.segments) == 95
        assert len(track.translations) == 95
        assert len(track.audio) == 95
        assert len(track.alignments) == 95
        assert len(track.timeline) == 95
        assert track.qa is not None and len(track.qa.segments) == 95
        for path in track.exports:
            assert os.path.exists(path), path


def test_silent_tts_writes_a_clip_of_the_predicted_length():
    """Everything downstream measures against this file, so its duration has to
    be the prediction - within one sample frame of rounding."""
    with tempfile.TemporaryDirectory() as out:
        _, track = _run(out_dir=out)
        by_id = {t.segment_id: t for t in track.translations}
        for asset in track.audio:
            with wave.open(asset.path, "rb") as handle:
                on_disk = handle.getnframes() / handle.getframerate()
            assert abs(on_disk - by_id[asset.segment_id].predicted_duration) < 0.001
            assert abs(on_disk - asset.duration) < 1e-9


def test_echo_translator_reproduces_module_1s_budget_analysis():
    """The stub track must agree with the parser's own numbers. When a real
    translator arrives, this is the baseline it has to beat."""
    with tempfile.TemporaryDirectory() as out:
        _, english = _run(out_dir=out)
        assert len(english.unfitted) == 42
        assert english.qa is not None
        assert len(english.qa.drift_failures) == 42
        assert round(sum(a.duration for a in english.audio)) == 536

    with tempfile.TemporaryDirectory() as out:
        _, tamil = _run(TAMIL, "ta", out_dir=out)
        assert len(tamil.unfitted) == 83
        assert round(sum(a.duration for a in tamil.audio)) == 770


def test_timeline_anchors_on_the_script_timestamps():
    with tempfile.TemporaryDirectory() as out:
        script, track = _run(out_dir=out)
        for segment, item in zip(script.segments, track.timeline):
            assert item.start == segment.start
        anchored = [i for i in track.timeline if i.anchored]
        assert len(anchored) == 11  # one per action cue


def test_early_finishing_narration_is_not_a_sync_failure():
    """A clip shorter than its window leaves a gap for Step 3 to hold, not
    drift. Only overrun breaks sync."""
    with tempfile.TemporaryDirectory() as out:
        _, track = _run(out_dir=out)
        assert track.qa is not None
        under = [s for s in track.qa.segments if s.drift < -1.0]
        assert under, "the English track has segments that finish early"
        assert all(s.within_drift for s in under)


def test_srt_is_written_and_timed_from_the_timeline():
    with tempfile.TemporaryDirectory() as out:
        _, track = _run(out_dir=out)
        srt = [p for p in track.exports if p.endswith(".srt")][0]
        with open(srt, encoding="utf-8") as handle:
            body = handle.read()
        assert body.startswith("1\n00:00:01,000 --> ")
        assert "Welcome to the Spoken Tutorial" in body
        assert body.count(" --> ") == 95


class _ShorterTranslator:
    """Stands in for an author correcting one segment by hand."""

    name = "shorter"

    def translate(self, segment, *, target_language, model):
        text = "Short."
        return TranslatedSegment(
            segment_id=segment.id,
            language=target_language,
            source_text=segment.text,
            text=text,
            syllables=1,
            predicted_duration=model.estimate(text, target_language),
            budget=segment.narration_budget,
            translator=self.name,
        )


def test_a_single_segment_can_be_regenerated_alone():
    """UC-03: correcting one segment must not cost a full re-run."""
    from app.pipeline import registry

    with tempfile.TemporaryDirectory() as out:
        script, track = _run(out_dir=out)
        before = {t.segment_id: t.text for t in track.translations}
        target = script.segments[3].id

        registry.TRANSLATORS["shorter"] = _ShorterTranslator
        try:
            config = PipelineConfig(language="en", out_dir=out, translator="shorter")
            track = run_segments(script, track, [target], config)
        finally:
            del registry.TRANSLATORS["shorter"]

        changed = {t.segment_id: t.text for t in track.translations}
        assert changed[target] == "Short."
        assert len(changed) == 95
        untouched = [k for k in before if k != target and before[k] != changed[k]]
        assert not untouched, untouched
        assert track.qa is not None and len(track.qa.segments) == 95


class _EightKilohertzTTS:
    """A second TTS provider, differing only in what it writes."""

    name = "loud"

    def __init__(self):
        from app.tts.silent import SilentTTS

        self.inner = SilentTTS(sample_rate=8000)

    def synthesize(self, translated, *, out_path, voice=None):
        asset = self.inner.synthesize(translated, out_path=out_path, voice=voice)
        asset.provider = self.name
        return asset


def test_swapping_a_provider_does_not_change_the_track_shape():
    """HLD UC-07: a provider change must not alter project data."""
    from app.pipeline import registry

    with tempfile.TemporaryDirectory() as out:
        script = parse_script(ENGLISH, language="en", duration=VIDEO_DURATION)
        baseline = run_track(script, PipelineConfig(language="en", out_dir=out))

        registry.TTS_PROVIDERS["loud"] = _EightKilohertzTTS
        try:
            swapped = run_track(
                script, PipelineConfig(language="en", out_dir=out, tts="loud")
            )
        finally:
            del registry.TTS_PROVIDERS["loud"]

        assert [a.segment_id for a in swapped.audio] == [
            a.segment_id for a in baseline.audio
        ]
        assert all(a.provider == "loud" for a in swapped.audio)
        assert all(a.sample_rate == 8000 for a in swapped.audio)
        assert [t.text for t in swapped.translations] == [
            t.text for t in baseline.translations
        ]
        assert swapped.qa is not None and baseline.qa is not None
        assert len(swapped.qa.segments) == len(baseline.qa.segments)


def _qa(*drifts: float) -> QAReport:
    return QAReport(
        language="en",
        segments=[
            SegmentQA(
                segment_id=f"s{i}",
                budget=1.0,
                predicted=1.0,
                actual=1.0 + drift,
                drift=drift,
                rate_ratio=1.0,
            )
            for i, drift in enumerate(drifts)
        ],
    )


def test_max_drift_and_largest_gap_never_go_negative():
    """Overrun and gap are one-sided: a track with no overrun has max_drift 0,
    a track with no slack has largest_gap 0. They must not swap signs."""
    early = _qa(-13.33, -1.0, -0.2)
    assert early.max_drift == 0.0
    assert early.largest_gap == 13.33

    late = _qa(3.0, 0.1, 1.5)
    assert late.max_drift == 3.0
    assert late.largest_gap == 0.0

    mixed = _qa(-2.5, 1.25, -0.1)
    assert mixed.max_drift == 1.25
    assert mixed.largest_gap == 2.5

    empty = QAReport(language="en")
    assert empty.max_drift == 0.0
    assert empty.largest_gap == 0.0


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
