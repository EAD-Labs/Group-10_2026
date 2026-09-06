"""Tests for the stubbed end-to-end pipeline.

The point of Step 2 is that the chain runs and the seams hold, so these tests
check plumbing and arithmetic, not narration quality - there is no narration
yet. Two things they pin down that will matter when the stubs are replaced:

  * the stub numbers agree with the Step 1 duration model - the one calibrated
    against the client's recordings - so a future translator's improvement is
    measured against a baseline that is known to be right
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
from app.duration.model import RateModel  # noqa: E402
from app.export.subtitles import _timestamp  # noqa: E402
from app.media.vad import detect_speech  # noqa: E402
from app.schemas import (  # noqa: E402
    AlignmentResult,
    AudioAsset,
    QAReport,
    SegmentQA,
    TranslatedSegment,
)
from app.timeline.builder import build_timeline  # noqa: E402
from app.tts.silent import write_silence  # noqa: E402

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


def test_echo_translator_agrees_with_the_step_1_model():
    """The stub track must agree with the calibrated duration model. When a
    real translator arrives, this is the baseline it has to beat.

    These numbers moved when Step 1 replaced the script-derived pace (3.00
    syl/s, which had silently averaged the pauses in) with the measured
    articulation rate (3.91) and began reserving the pause. They are lower and
    they are right."""
    with tempfile.TemporaryDirectory() as out:
        _, english = _run(out_dir=out)
        assert len(english.unfitted) == 11
        assert english.qa is not None
        assert len(english.qa.drift_failures) == 11
        assert round(sum(a.duration for a in english.audio)) == 411

    with tempfile.TemporaryDirectory() as out:
        _, tamil = _run(TAMIL, "ta", out_dir=out)
        assert len(tamil.unfitted) == 63
        assert round(sum(a.duration for a in tamil.audio)) == 591


def test_the_translator_is_not_given_the_pause_to_spend():
    """Step 1's central finding, enforced.

    A segment's window is speech plus the pause the narrator has to leave. The
    translator must be handed the speech half only - otherwise it produces a
    track where every line fits and none of them breathe, which is exactly the
    delivery the client complained about."""
    script = parse_script(ENGLISH, language="en", duration=VIDEO_DURATION)
    model = RateModel()
    translator = get_translator("echo")

    for segment in script.segments[:20]:
        result = translator.translate(segment, target_language="en", model=model)
        assert result.budget == model.speaking_budget(segment)
        if segment.narration_budget > model.pause_reserve:
            assert result.budget < segment.narration_budget


def test_qa_reports_the_pause_not_only_the_drift():
    """The Tamil script is the case that proves drift alone is insufficient.

    Run against the client's own delivered Tamil text, the report has to show
    what Step 1 measured in their audio: the pauses are gone. A report that
    only tracked drift would rate this track far more kindly than it sounds."""
    with tempfile.TemporaryDirectory() as out:
        _, tamil = _run(TAMIL, "ta", out_dir=out)
    with tempfile.TemporaryDirectory() as out:
        _, english = _run(out_dir=out)

    assert tamil.qa.median_pause == 0.0
    assert english.qa.median_pause > 0.5
    assert tamil.qa.segments_without_pause > english.qa.segments_without_pause * 3

    # Independent agreement: Step 1 measured a 0.00 s median pause in the
    # delivered Tamil AUDIO; this predicts the same from the TEXT alone.
    assert all(not s.unrushed for s in tamil.qa.segments if s.pause_after == 0.0)


def test_over_budget_cannot_disagree_with_within_drift():
    row = SegmentQA(
        segment_id="S-001", budget=5.0, predicted=4.0, actual=4.0,
        drift=-1.0, pause_after=1.4, rate_ratio=1.0, within_drift=True,
    )
    assert row.over_budget is False
    assert row.unrushed is True
    assert "over_budget" in row.model_dump()


def test_timeline_trims_the_lead_in_silence():
    """A generated clip opens with silence before the first word. The speech,
    not the file, is what has to land on the segment's timestamp."""
    script = parse_script(ENGLISH, language="en", duration=VIDEO_DURATION)
    segment = script.segments[0]
    asset = AudioAsset(
        segment_id=segment.id, language="en", path="unused.wav", duration=4.0
    )
    alignment = AlignmentResult(
        segment_id=segment.id, speech_start=0.3, speech_end=3.8, aligner="test"
    )
    item = build_timeline(script, [asset], [alignment])[0]

    assert item.audio_offset == 0.3
    assert item.start == segment.start
    assert abs((item.end - item.start) - 3.5) < 1e-9


def test_srt_timestamps_never_render_a_sixtieth_second():
    assert _timestamp(59.9996) == "00:01:00,000"
    assert _timestamp(119.9999) == "00:02:00,000"
    assert _timestamp(3599.9999) == "01:00:00,000"
    assert _timestamp(663.2) == "00:11:03,200"


def test_the_vad_aligner_is_the_step_1_detector():
    """Alignment and Step 1's measurement must answer 'where is the speech'
    with the same code, or the QA report cannot be compared against what was
    measured on the client's audio."""
    audio = os.path.join(MATERIALS, "work", "audio", "synfig-English.wav")
    if not os.path.exists(audio):
        return  # client media absent on this machine

    aligner = get_aligner("vad")
    result = aligner.align(
        AudioAsset(segment_id="S-001", language="en", path=audio, duration=663.2), ""
    )
    assert result.aligner == "vad"
    assert 0.0 < result.speech_start < 5.0
    assert result.speech_duration > 600.0


def test_a_silent_clip_reports_no_speech_rather_than_all_speech():
    """The threshold is relative to the file's own loud level, which inverts on
    a file with no dynamic range. SilentTTS emits exactly such files."""
    with tempfile.TemporaryDirectory() as out:
        path = os.path.join(out, "silence.wav")
        write_silence(path, 2.0)
        track = detect_speech(path)
        assert track.speech_seconds == 0.0


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
