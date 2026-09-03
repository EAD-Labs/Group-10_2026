"""Voice activity detection: which parts of a recording are speech?

Step 0 budgets narration by the gap between script timestamps, which silently
assumes the narrator talks for the whole window. They do not - the client's own
dubbing instructions require "an appropriate pause between sentences". This
module measures where the speech actually is, so the budget can reserve that
pause instead of handing it to the translator as speaking time.

Energy-based rather than model-based on purpose: it needs no download, behaves
identically on Tamil and English, and has no ASR accuracy to distrust. Word-level
forced alignment is a separate concern, needed later to measure drift on
generated audio.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import soundfile as sf

FRAME_SECONDS = 0.010
THRESHOLD_BELOW_LOUD_DB = 30.0
"""Speech threshold, in dB below the recording's 90th-percentile level.

Anchored to the loud level rather than the noise floor because the two tracks
have wildly different floors: the English original sits at about -84 dB, while
the Tamil dub - assembled by splicing clips - has stretches of true digital
silence at -200 dB. A floor-relative threshold is unstable across them; a
loud-relative one is not, and the measured speech fraction moves less than two
points across a +/-15 dB sweep of this constant.
"""

FILL_GAP_MS = 200.0
"""Silences shorter than this are inside a word or between words, not a pause."""

DROP_RUN_MS = 80.0
"""Speech bursts shorter than this are clicks or breaths, not speech."""


@dataclass
class SpeechTrack:
    """A frame-level speech/silence mask over one audio file."""

    mask: np.ndarray
    frame_seconds: float
    threshold_db: float

    @property
    def duration(self) -> float:
        return len(self.mask) * self.frame_seconds

    @property
    def speech_seconds(self) -> float:
        return float(self.mask.sum()) * self.frame_seconds

    def window(self, start: float, end: float) -> np.ndarray:
        first = max(int(round(start / self.frame_seconds)), 0)
        last = min(int(round(end / self.frame_seconds)), len(self.mask))
        return self.mask[first:last]

    def speech_in(self, start: float, end: float) -> float:
        return float(self.window(start, end).sum()) * self.frame_seconds

    def trailing_silence(self, start: float, end: float) -> float:
        """Silence at the end of a window - the pause before the next line."""
        window = self.window(start, end)
        silent = 0
        for value in window[::-1]:
            if value:
                break
            silent += 1
        return silent * self.frame_seconds

    def leading_silence(self, start: float, end: float) -> float:
        window = self.window(start, end)
        silent = 0
        for value in window:
            if value:
                break
            silent += 1
        return silent * self.frame_seconds


def frame_energy_db(path: str, frame_seconds: float = FRAME_SECONDS) -> np.ndarray:
    samples, sample_rate = sf.read(path, dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)

    per_frame = int(sample_rate * frame_seconds)
    usable = len(samples) - (len(samples) % per_frame)
    frames = samples[:usable].reshape(-1, per_frame).astype(np.float64)
    rms = np.sqrt((frames**2).mean(axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-10))


def _smooth(mask: np.ndarray, frame_seconds: float) -> np.ndarray:
    """Close short gaps, then drop short bursts. Order matters: closing first
    means a stutter inside a word cannot fragment it into sub-threshold runs."""
    smoothed = mask.copy()
    for target, limit_ms in ((False, FILL_GAP_MS), (True, DROP_RUN_MS)):
        runs: list[tuple[int, int, bool]] = []
        start = 0
        for index in range(1, len(smoothed) + 1):
            if index == len(smoothed) or smoothed[index] != smoothed[start]:
                runs.append((start, index, bool(smoothed[start])))
                start = index
        for first, last, value in runs:
            if value == target and (last - first) * frame_seconds * 1000 < limit_ms:
                smoothed[first:last] = not target
    return smoothed


def detect_speech(path: str, frame_seconds: float = FRAME_SECONDS) -> SpeechTrack:
    energy = frame_energy_db(path, frame_seconds)
    threshold = float(np.percentile(energy, 90)) - THRESHOLD_BELOW_LOUD_DB
    mask = _smooth(energy > threshold, frame_seconds)
    return SpeechTrack(mask=mask, frame_seconds=frame_seconds, threshold_db=threshold)
