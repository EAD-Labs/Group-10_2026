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
