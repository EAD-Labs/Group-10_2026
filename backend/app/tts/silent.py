"""SilentTTS - the synthesis stub.

Emits a WAV of exactly the predicted duration: silence, but silence of the
right length. That is enough for the timeline to build, the drift arithmetic
to run, the SRT to be timed and the export to be assembled, so every stage
downstream of synthesis can be developed and demoed before a single TTS
credit is spent.

Written with the stdlib `wave` module - no ffmpeg, no provider account, no
network. Deliberately: this stub must never be the reason the pipeline cannot
run on a teammate's machine.
"""

from __future__ import annotations

import os
import wave

from ..schemas import AudioAsset, TranslatedSegment

SAMPLE_RATE = 22050
SAMPLE_WIDTH = 2  # 16-bit PCM
CHANNELS = 1


def write_silence(path: str, seconds: float, sample_rate: int = SAMPLE_RATE) -> float:
    """Write `seconds` of silence and return the duration actually written.

    The return value is the file's true duration after frame rounding, not the
    requested figure: downstream QA compares predicted against actual, and that
    comparison is worthless if 'actual' is just the prediction handed back.
    """
    frames = max(int(round(seconds * sample_rate)), 0)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00" * (frames * SAMPLE_WIDTH * CHANNELS))
    return frames / sample_rate


class SilentTTS:
    """Produces a silent clip of the predicted length."""

    name = "silent"

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate

    def synthesize(
        self, translated: TranslatedSegment, *, out_path: str, voice: str | None = None
    ) -> AudioAsset:
        duration = write_silence(out_path, translated.predicted_duration, self.sample_rate)
        return AudioAsset(
            segment_id=translated.segment_id,
            language=translated.language,
            path=out_path,
            duration=duration,
            sample_rate=self.sample_rate,
            provider=self.name,
            voice=voice,
        )
