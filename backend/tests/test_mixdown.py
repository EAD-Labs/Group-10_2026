"""Tests for the mixdown: clips land at the right samples, cue windows carry
the base video's audio, and the full pipeline writes a playable track."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from app.export.mixdown import mix  # noqa: E402
from app.pipeline.runner import PipelineConfig, run_pipeline  # noqa: E402
from app.schemas import ActionCue, LanguageTrack, ParsedScript, TimelineItem  # noqa: E402
from tests._paths import ENGLISH_SCRIPT  # noqa: E402

RATE = 1000  # a coarse rate keeps sample arithmetic readable


def _wav(path: str, values: list[float]) -> str:
    sf.write(path, np.array(values, dtype="float32"), RATE, subtype="FLOAT")
    return path


def test_clips_are_placed_at_their_start_with_the_lead_in_trimmed():
    with tempfile.TemporaryDirectory() as out:
        clip = _wav(os.path.join(out, "c.wav"), [0.0] * 100 + [0.5] * 200)
        track = LanguageTrack(
            source="s", language="ta", duration=2.0,
            timeline=[TimelineItem(segment_id="S-001", start=1.0, end=1.2,
                                   audio_path=clip, audio_offset=0.1)],
        )
        samples = mix(track, sample_rate=RATE)

    assert len(samples) == 2000
    assert not samples[:1000].any()
    assert np.allclose(samples[1000:1200], 0.5)  # speech lands exactly on 1.0 s
    assert not samples[1200:].any()


def test_cue_windows_carry_the_base_videos_audio():
    with tempfile.TemporaryDirectory() as out:
        base = _wav(os.path.join(out, "base.wav"), [0.25] * 3000)
        script = ParsedScript(
            source="s", language="en", duration=3.0,
            cues=[ActionCue(id="C-1", at=1.0, raw="@00:01", description="clip",
                            clip_duration=0.5)],
        )
        track = LanguageTrack(source="s", language="ta", duration=3.0)
        samples = mix(track, script, base, sample_rate=RATE)

    assert not samples[:1000].any()
    assert np.allclose(samples[1000:1500], 0.25)
    assert not samples[1500:].any()


def test_the_pipeline_writes_a_dub_the_length_of_the_video():
    with tempfile.TemporaryDirectory() as out:
        config = PipelineConfig(language="en", out_dir=out, exporters=["srt", "mixdown"])
        _, track = run_pipeline(ENGLISH_SCRIPT, config, duration=663.2)
        dub = [p for p in track.exports if p.endswith("-dub.wav")]
        assert dub, track.exports
        info = sf.info(dub[0])
        assert abs(info.frames / info.samplerate - 663.2) < 0.01
