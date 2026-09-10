"""ClipBoundsAligner - the alignment stub.

A real aligner (WhisperX or MFA, Step 1 of the build plan) finds where speech
actually begins and ends inside a clip. This stub reads the clip's own
boundaries from the WAV header, which is exactly right for SilentTTS - a
generated clip of predicted length has no lead-in to trim - and exactly wrong
for real narration.

It reads the file rather than trusting AudioAsset.duration on purpose: that
keeps the honest measurement path in place, so swapping in WhisperX changes
what is measured, not whether anything is.
"""

from __future__ import annotations

import contextlib
import os
import wave

from ..schemas import AlignmentResult, AudioAsset


def wav_duration(path: str) -> float:
    """Duration of a WAV file in seconds, or 0.0 if it cannot be read."""
    if not os.path.exists(path):
        return 0.0
    with contextlib.suppress(wave.Error, EOFError), wave.open(path, "rb") as handle:
        rate = handle.getframerate()
        return handle.getnframes() / rate if rate else 0.0
    return 0.0


class ClipBoundsAligner:
    """Treats the whole clip as speech."""

    name = "clip-bounds"

    def align(self, audio: AudioAsset, text: str) -> AlignmentResult:
        duration = wav_duration(audio.path) or audio.duration
        return AlignmentResult(
            segment_id=audio.segment_id,
            speech_start=0.0,
            speech_end=duration,
            aligner=self.name,
        )
