"""Measure a delivered recording against its script, and calibrate from it.

This is what turns the duration model from a guess into a measurement. Given a
parsed script and the audio that was actually recorded for it, we get, per
segment: how long the narrator really spoke, and how long they paused.

Windows containing an embedded clip are excluded. Those hold narration from a
different tutorial entirely - 90 s of the Synfig sample - and measuring them
would attribute another tutorial's speech to this script's syllables. Step 0's
cue detection is what makes that exclusion possible.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from ..media.vad import SpeechTrack
from ..schemas import NO_PERCEPTIBLE_PAUSE, ParsedScript


@dataclass
class SegmentMeasurement:
    segment_id: str
    syllables: int
    window: float
    speech: float
    trailing_pause: float
    leading_silence: float

    @property
    def fill_ratio(self) -> float:
        return self.speech / self.window if self.window > 0 else 0.0

    @property
    def articulation_rate(self) -> float:
        """Syllables per second of actual speech - not per second of window."""
        return self.syllables / self.speech if self.speech > 0 else 0.0


@dataclass
class Calibration:
    language: str
    articulation_rate: float
    """Median syllables per second of real speech."""

    aggregate_rate: float
    """Total syllables over total speech time; less sensitive to short segments."""

    pause_median: float
    """Typical silence at the end of a segment."""

    speech_fraction: float
    """Share of window time that is actually speech."""

    segments_measured: int
    segments_without_pause: int

    def summary(self) -> str:
        return (
            f"{self.language}: {self.articulation_rate:.2f} syl/s articulation, "
            f"{self.pause_median:.2f}s median pause, "
            f"{self.speech_fraction * 100:.1f}% of window is speech "
            f"({self.segments_measured} segments)"
        )


MIN_SPEECH_FOR_RATE = 0.30
"""Segments with less speech than this are too short to estimate a rate from."""

NO_PAUSE_THRESHOLD = NO_PERCEPTIBLE_PAUSE
"""Re-exported from schemas so the QA report on generated audio and the
measurement of delivered audio cannot drift apart."""


def measure_script(
    script: ParsedScript,
    track: SpeechTrack,
    *,
    skip_cue_windows: bool = True,
) -> list[SegmentMeasurement]:
    measurements = []
    for segment in script.segments:
        if skip_cue_windows and segment.cue_ids:
            continue
        if segment.end <= segment.start:
            continue
        measurements.append(
            SegmentMeasurement(
                segment_id=segment.id,
                syllables=segment.syllables,
                window=segment.end - segment.start,
                speech=track.speech_in(segment.start, segment.end),
                trailing_pause=track.trailing_silence(segment.start, segment.end),
                leading_silence=track.leading_silence(segment.start, segment.end),
            )
        )
    return measurements


def calibrate(
    script: ParsedScript,
    track: SpeechTrack,
    *,
    skip_cue_windows: bool = True,
) -> Calibration:
    measurements = measure_script(script, track, skip_cue_windows=skip_cue_windows)
    if not measurements:
        raise ValueError(f"{script.source}: no measurable segments")

    rates = [m.articulation_rate for m in measurements if m.speech >= MIN_SPEECH_FOR_RATE]
    total_speech = sum(m.speech for m in measurements)
    total_window = sum(m.window for m in measurements)
    total_syllables = sum(m.syllables for m in measurements)

    return Calibration(
        language=script.language,
        articulation_rate=statistics.median(rates) if rates else 0.0,
        aggregate_rate=total_syllables / total_speech if total_speech else 0.0,
        pause_median=statistics.median([m.trailing_pause for m in measurements]),
        speech_fraction=total_speech / total_window if total_window else 0.0,
        segments_measured=len(measurements),
        segments_without_pause=sum(
            1 for m in measurements if m.trailing_pause < NO_PAUSE_THRESHOLD
        ),
    )
