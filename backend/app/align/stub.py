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

from ..media.audio import wav_duration
from ..schemas import AlignmentResult, AudioAsset

__all__ = ["ClipBoundsAligner", "wav_duration"]


class ClipBoundsAligner:
    """Treats the whole clip as speech."""

    name = "clip-bounds"
    is_stub = True

    def align(self, audio: AudioAsset, text: str) -> AlignmentResult:
        duration = wav_duration(audio.path) or audio.duration
        return AlignmentResult(
            segment_id=audio.segment_id,
            speech_start=0.0,
            speech_end=duration,
            aligner=self.name,
        )
