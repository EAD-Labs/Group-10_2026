"""VadAligner - alignment by the Step 1 measurement machinery.

Step 1 built a speech detector to measure the client's delivered recordings.
The pipeline's alignment stage asks the same question of a generated clip -
where inside this file is the speech? - so it is answered by the same code
rather than by a second implementation that could disagree with it.

That matters beyond tidiness: the QA report compares a generated track against
the numbers Step 1 measured on the client's audio. If the two were measured by
different detectors the comparison would be meaningless.

Pair this with a TTS provider that produces real audio. Against SilentTTS it
correctly reports no speech at all, which is why `clip-bounds` remains the
default stub - a silent clip has no speech to find, and saying so is the
honest answer rather than a bug.
"""

from __future__ import annotations

from ..media.vad import detect_speech
from ..schemas import AlignmentResult, AudioAsset


class VadAligner:
    """Finds the first and last speech frames in a clip."""

    name = "vad"

    def align(self, audio: AudioAsset, text: str) -> AlignmentResult:
        track = detect_speech(audio.path)

        speech_frames = [i for i, active in enumerate(track.mask) if active]
        if not speech_frames:
            return AlignmentResult(
                segment_id=audio.segment_id,
                speech_start=0.0,
                speech_end=0.0,
                aligner=self.name,
            )

        return AlignmentResult(
            segment_id=audio.segment_id,
            speech_start=speech_frames[0] * track.frame_seconds,
            speech_end=(speech_frames[-1] + 1) * track.frame_seconds,
            aligner=self.name,
        )
