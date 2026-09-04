"""Data model for a parsed Spoken Tutorial timed script.

A timed script is a two-column table:  Time | Narration.

Two kinds of row appear in it:
  * narration rows - carry a MM:SS timestamp and the words the dubber speaks
  * cue rows       - carry no timestamp; the narration cell begins with "@MM:SS"
                     and instructs the editor to splice in audio from another
                     tutorial (e.g. "@04:56 Add the audio of Bouncing ball
                     tutorial from 05:44 to 05:51")

The distinction matters for timing.  A narration row's window runs to the next
narration row, but if a cue fires inside that window the embedded clip occupies
part of it, so the narration itself gets less time than the window suggests.
See Segment.narration_budget.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["error", "warning"]


class Violation(BaseModel):
    """A pedagogy-rule breach, reported against a segment (and optionally one
    sentence inside it)."""

    rule: str
    severity: Severity
    message: str
    sentence_index: int | None = None


class Sentence(BaseModel):
    index: int
    text: str
    char_count: int
    syllables: int = 0
    violations: list[Violation] = Field(default_factory=list)


class ActionCue(BaseModel):
    """An editing directive anchored to a point on the base video."""

    id: str
    at: float
    raw: str
    description: str
    clip_start: float | None = None
    clip_end: float | None = None
    clip_duration: float = 0.0


class Segment(BaseModel):
    """One narration row, with its timing budget resolved."""

    id: str
    index: int
    start: float
    end: float

    raw_budget: float
    """end - start: the whole window before the next narration row."""

    cue_reserved: float
    """Seconds inside the window taken by embedded clip audio."""

    narration_budget: float
    """raw_budget - cue_reserved - trailing_slack: what the narration may
    actually occupy. This is the number the duration-fitting engine must
    respect, and it is NOT raw_budget whenever a cue fires in the window."""

    trailing_slack: float = 0.0
    """Free time after an embedded clip finishes and before the next narration
    row starts. Genuinely available to the timeline generator for holds -
    unlike cue_reserved, which only looks free."""

    text: str
    char_count: int
    syllables: int = 0
    sentences: list[Sentence] = Field(default_factory=list)
    cue_ids: list[str] = Field(default_factory=list)
    bold_terms: list[str] = Field(default_factory=list)
    """Terms in bold face. Per the client's translation instructions these are
    never translated, only transliterated."""

    violations: list[Violation] = Field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(v.severity == "error" for v in self.violations)


class ParsedScript(BaseModel):
    source: str
    language: str
    duration: float
    """Total length of the base video, in seconds."""

    segments: list[Segment] = Field(default_factory=list)
    cues: list[ActionCue] = Field(default_factory=list)

    @property
    def violations(self) -> list[Violation]:
        return [v for s in self.segments for v in s.violations]

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "warning")

    @property
    def narration_budget_total(self) -> float:
        return sum(s.narration_budget for s in self.segments)


# ---------------------------------------------------------------------------
# Pipeline artefacts
#
# Everything below is produced by the stages downstream of parsing.  These are
# the shapes the whole team codes against: a stage may be a stub today and the
# real thing next week, but what it hands to the next stage does not change.
# Names follow the HLD's data entities (S8.2) so the eventual database schema
# is a transcription of this file rather than a redesign.
# ---------------------------------------------------------------------------


class TranslatedSegment(BaseModel):
    """One segment rendered into a target language, under its time budget."""

    segment_id: str
    language: str
    source_text: str
    text: str

    syllables: int = 0
    predicted_duration: float = 0.0
    """What the rate model thinks this text takes to say."""

    budget: float = 0.0
    """The segment's narration_budget - the number this text has to fit."""

    attempts: int = 1
    """Rephrasing rounds the translator needed. 1 means it fit first time."""

    fitted: bool = True
    """False when the translator gave up: predicted_duration still exceeds
    budget after the iteration cap. The author is asked to intervene (HLD
    S6.1 M2 - 'escalates unfittable segments to the author')."""

    translator: str = "echo"

    @property
    def overrun(self) -> float:
        return self.predicted_duration - self.budget


class AudioAsset(BaseModel):
    """A synthesised narration clip on disk."""

    segment_id: str
    language: str
    path: str
    duration: float
    sample_rate: int = 22050
    provider: str = "silent"
    voice: str | None = None


class AlignmentResult(BaseModel):
    """Where the speech actually sits inside a synthesised clip.

    A TTS clip is not wall-to-wall speech: it carries lead-in and trailing
    silence.  Drift is a property of the speech, not of the file, so the
    timeline anchors on speech_start rather than on the clip boundary.
    """

    segment_id: str
    speech_start: float
    speech_end: float
    aligner: str = "stub"

    @property
    def speech_duration(self) -> float:
        return max(self.speech_end - self.speech_start, 0.0)


class TimelineItem(BaseModel):
    """One narration clip placed on the base video's timeline."""

    segment_id: str
    start: float
    """Where the clip is placed on the base video, in seconds."""

    end: float
    audio_path: str
    hold_after: float = 0.0
    """Seconds of video hold inserted after this clip. Only ever non-zero at a
    non-action gap (HLD S13.1)."""

    anchored: bool = False
    """True when an action cue fires in this segment's window, which makes the
    boundary frame-locked: nothing may be inserted here."""


class SegmentQA(BaseModel):
    segment_id: str
    budget: float
    predicted: float
    actual: float
    drift: float
    """actual - budget. Positive means the narration runs past its window."""

    rate_ratio: float
    """Delivered pace over the reference pace. 1.0 is the target."""

    over_budget: bool = False
    within_drift: bool = True


class QAReport(BaseModel):
    """The objective report that gates approval and export (HLD S8.3)."""

    language: str
    segments: list[SegmentQA] = Field(default_factory=list)
    reference_rate: float = 0.0

    @property
    def max_drift(self) -> float:
        """The worst overrun: how far the most badly-fitting segment runs past
        its slot. Deliberately NOT max(abs(drift)) - the biggest number in the
        track is usually a segment that finishes early, and reporting that as
        "max drift" puts a harmless silence at the top of the QA report while
        the real overrun hides below it."""
        return max(0.0, max((s.drift for s in self.segments), default=0.0))

    @property
    def largest_gap(self) -> float:
        """The longest silence left after a segment finishes early. Not a
        failure - it is the raw material Step 3 turns into holds."""
        return max(0.0, -min((s.drift for s in self.segments), default=0.0))

    @property
    def mean_rate_ratio(self) -> float:
        ratios = [s.rate_ratio for s in self.segments if s.rate_ratio > 0]
        return sum(ratios) / len(ratios) if ratios else 0.0

    @property
    def over_budget_count(self) -> int:
        return sum(1 for s in self.segments if s.over_budget)

    @property
    def drift_failures(self) -> list[SegmentQA]:
        return [s for s in self.segments if not s.within_drift]


class LanguageTrack(BaseModel):
    """One language's worth of everything: the unit that gets approved,
    exported, and re-run a single segment at a time."""

    source: str
    language: str
    duration: float

    translations: list[TranslatedSegment] = Field(default_factory=list)
    audio: list[AudioAsset] = Field(default_factory=list)
    alignments: list[AlignmentResult] = Field(default_factory=list)
    timeline: list[TimelineItem] = Field(default_factory=list)
    qa: QAReport | None = None
    exports: list[str] = Field(default_factory=list)

    @property
    def unfitted(self) -> list[TranslatedSegment]:
        return [t for t in self.translations if not t.fitted]
