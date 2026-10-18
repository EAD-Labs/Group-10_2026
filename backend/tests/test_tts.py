"""Tests for real speech synthesis: the Sarvam provider and pace correction.

No network: Sarvam's endpoint is replaced by a function that returns a real
base64 WAV, so request shape, decoding, measurement and caching are all
exercised exactly as against the live API.
"""

from __future__ import annotations

import base64
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from app.duration.model import DRIFT_TOLERANCE, RATE_TOLERANCE  # noqa: E402
from app.parsing.parser import parse_script  # noqa: E402
from app.pipeline import registry  # noqa: E402
from app.pipeline.interfaces import TTSProvider  # noqa: E402
from app.pipeline.runner import PipelineConfig, pace_for, run_track  # noqa: E402
from app.schemas import TranslatedSegment  # noqa: E402
from app.tts.sarvam import SarvamTTS, TTSError  # noqa: E402
from app.tts.silent import write_silence  # noqa: E402
from tests._paths import ENGLISH_SCRIPT  # noqa: E402

VIDEO_DURATION = 663.2


def _tone(seconds: float, rate: int = 22050) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    buffer = io.BytesIO()
    sf.write(buffer, (0.3 * np.sin(2 * np.pi * 220 * t)).astype("float32"), rate,
             format="WAV", subtype="PCM_16")
    return buffer.getvalue()


class _Response:
    def __init__(self, status: int, body: dict | None = None, text: str = "") -> None:
        self.status_code = status
        self._body = body or {}
        self.text = text
        self.headers: dict = {}

    def json(self):
        return self._body


class _FakeSarvam:
    """Replaces httpx.post; records each request."""

    def __init__(self, seconds: float = 1.5, failures: int = 0) -> None:
        self.seconds = seconds
        self.failures = failures
        self.requests: list[dict] = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.requests.append({"url": url, "json": json, "headers": headers})
        if self.failures:
            self.failures -= 1
            return _Response(429, text="rate limited, try again in 0.0s")
        audio = base64.b64encode(_tone(self.seconds)).decode("ascii")
        return _Response(200, {"request_id": "r1", "audios": [audio]})


def _patched(fake):
    import httpx

    original = httpx.post
    httpx.post = fake
    return lambda: setattr(httpx, "post", original)


def _translated(text: str = "வணக்கம் Synfig", language: str = "ta") -> TranslatedSegment:
    return TranslatedSegment(
        segment_id="S-001", language=language, source_text="Hello Synfig", text=text,
        syllables=5, predicted_duration=1.2, budget=2.0,
    )


def test_sarvam_satisfies_the_tts_protocol():
    tts = SarvamTTS(api_key="k", cache_dir=None)
    assert isinstance(tts, TTSProvider)
    assert tts.supports_pace


def test_sarvam_request_shape_and_measured_duration():
    fake = _FakeSarvam(seconds=1.5)
    restore = _patched(fake)
    try:
        with tempfile.TemporaryDirectory() as out:
            tts = SarvamTTS(api_key="secret", cache_dir=None, speaker="vidya")
            asset = tts.synthesize(_translated(), out_path=os.path.join(out, "a.wav"), pace=1.05)

            # Measured from the decoded file, not the request.
            assert abs(asset.duration - 1.5) < 0.01
            assert asset.voice == "vidya"
            assert sf.info(asset.path).subtype == "PCM_16"
    finally:
        restore()

    request = fake.requests[0]
    assert request["url"].endswith("/text-to-speech")
    assert request["headers"] == {"api-subscription-key": "secret"}
    body = request["json"]
    assert body["language_code"] == "ta-IN"
    assert body["speaker"] == "vidya"
    assert body["pace"] == 1.05
    assert body["text"] == "வணக்கம் Synfig"


def test_sarvam_retries_a_rate_limit():
    fake = _FakeSarvam(failures=1)
    restore = _patched(fake)
    try:
        with tempfile.TemporaryDirectory() as out:
            SarvamTTS(api_key="k", cache_dir=None).synthesize(
                _translated(), out_path=os.path.join(out, "a.wav")
            )
    finally:
        restore()
    assert len(fake.requests) == 2


def test_sarvam_cache_stops_a_rerun_paying_twice():
    fake = _FakeSarvam()
    restore = _patched(fake)
    try:
        with tempfile.TemporaryDirectory() as out:
            tts = SarvamTTS(api_key="k", cache_dir=os.path.join(out, "cache"))
            tts.synthesize(_translated(), out_path=os.path.join(out, "a.wav"))
            tts.synthesize(_translated(), out_path=os.path.join(out, "b.wav"))
            assert len(fake.requests) == 1
            # A different pace is different audio.
            tts.synthesize(_translated(), out_path=os.path.join(out, "c.wav"), pace=1.1)
            assert len(fake.requests) == 2
    finally:
        restore()


def test_an_empty_translation_is_not_sent_to_sarvam():
    fake = _FakeSarvam()
    restore = _patched(fake)
    try:
        with tempfile.TemporaryDirectory() as out:
            asset = SarvamTTS(api_key="k", cache_dir=None).synthesize(
                _translated(text=""), out_path=os.path.join(out, "a.wav")
            )
            assert asset.duration == 0.0
    finally:
        restore()
    assert fake.requests == []


def test_sarvam_without_a_key_fails_with_a_usable_message():
    with tempfile.TemporaryDirectory() as out:
        try:
            SarvamTTS(api_key="", cache_dir=None).synthesize(
                _translated(), out_path=os.path.join(out, "a.wav")
            )
        except TTSError as error:
            assert "SARVAM_API_KEY" in str(error)
        else:
            raise AssertionError("expected TTSError")


# -- pace correction ----------------------------------------------------------


def test_pace_is_capped_at_the_rate_tolerance():
    assert pace_for(4.0, 5.0) == 1.0
    assert abs(pace_for(5.25, 5.0) - 1.05) < 1e-9
    assert pace_for(9.0, 5.0) == 1.0 + RATE_TOLERANCE


class _SlowVoice:
    """A voice that reads everything `overrun` too slowly, unless sped up."""

    name = "slow-voice"
    supports_pace = True
    overrun = 1.08

    def __init__(self) -> None:
        self.paces: list[float] = []

    def synthesize(self, translated, *, out_path, voice=None, pace=1.0):
        from app.schemas import AudioAsset

        self.paces.append(pace)
        seconds = translated.budget * self.overrun / pace
        duration = write_silence(out_path, seconds)
        return AudioAsset(segment_id=translated.segment_id, language=translated.language,
                          path=out_path, duration=duration, provider=self.name)


def test_an_overrunning_clip_is_resynthesised_faster_once():
    script = parse_script(ENGLISH_SCRIPT, language="en", duration=VIDEO_DURATION)
    voice = _SlowVoice()
    registry.TTS_PROVIDERS["slow-voice"] = lambda: voice
    try:
        with tempfile.TemporaryDirectory() as out:
            track = run_track(script, PipelineConfig(language="en", out_dir=out, tts="slow-voice"))
    finally:
        del registry.TTS_PROVIDERS["slow-voice"]

    corrected = [p for p in voice.paces if p != 1.0]
    over = [t for t in track.translations if t.budget * (_SlowVoice.overrun - 1) > DRIFT_TOLERANCE]
    assert len(corrected) == len(over) > 0
    assert all(abs(p - 1.08) < 1e-3 for p in corrected)  # within frame rounding
    qa = {row.segment_id: row for row in track.qa.segments}
    assert all(qa[t.segment_id].within_drift for t in over)


# -- base pace -----------------------------------------------------------------


def test_the_base_pace_is_sent_and_correction_is_relative_to_it():
    """An 0.8 track asks for every clip at 0.8, and an overrunning clip is
    corrected to at most 0.88 - +10% of the chosen pace, not of 1.0."""
    fake = _FakeSarvam(seconds=1.0)
    restore = _patched(fake)
    try:
        with tempfile.TemporaryDirectory() as out:
            tts = SarvamTTS(api_key="k", cache_dir=None, pace=0.8)
            tts.synthesize(_translated(), out_path=os.path.join(out, "a.wav"))
            tts.synthesize(_translated(), out_path=os.path.join(out, "b.wav"), pace=0.88)
    finally:
        restore()
    assert [r["json"]["pace"] for r in fake.requests] == [0.8, 0.88]

    voice = _SlowVoice()
    voice.pace = 1.0
    script = parse_script(ENGLISH_SCRIPT, language="en", duration=VIDEO_DURATION)
    registry.TTS_PROVIDERS["slow-voice"] = lambda: voice
    try:
        with tempfile.TemporaryDirectory() as out:
            run_track(script, PipelineConfig(language="en", out_dir=out, tts="slow-voice",
                                             voice_pace=0.8))
    finally:
        del registry.TTS_PROVIDERS["slow-voice"]
    assert voice.pace == 0.8
    corrected = [p for p in voice.paces if p != 1.0]
    assert corrected and all(abs(p - 0.8 * 1.08) < 1e-3 for p in corrected)


def test_calibrated_rates_are_looked_up_for_the_tracks_pace():
    import json

    from app.duration.model import RateModel, voice_key

    with tempfile.TemporaryDirectory() as out:
        path = os.path.join(out, "rates.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({voice_key("sarvam:bulbul:v3", "shubh", 0.8): {"ta": 4.9},
                       voice_key("sarvam:bulbul:v3", "shubh", 1.0): {"ta": 6.1}}, handle)
        slow = RateModel.for_voice(voice_key("sarvam:bulbul:v3", "shubh", 0.8), path)
        natural = RateModel.for_voice(voice_key("sarvam:bulbul:v3", "shubh"), path)
    assert slow.rate("ta") == 4.9 and natural.rate("ta") == 6.1
