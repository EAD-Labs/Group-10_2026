"""The seams the pipeline is built on.

The build plan is thin and end-to-end, not module by module: the whole chain
runs from day one with every hard stage faked, and the fakes are replaced one
at a time.  That only works if the fakes and the real implementations are
interchangeable, which is what these Protocols buy.

A stage may be a stub today (EchoTranslator, SilentTTS) and a Sarvam AI call
next week.  The runner does not know the difference, and neither does any
other stage - they exchange the artefacts in schemas.py, nothing else.

Protocols rather than base classes on purpose: a provider is anything with the
right method, so a test double needs no import from us.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..duration.model import RateModel
from ..schemas import (
    AlignmentResult,
    AudioAsset,
    LanguageTrack,
    Segment,
    TranslatedSegment,
)


@runtime_checkable
class Translator(Protocol):
    """Renders one segment into a target language under its time budget.

    The budget is `model.speaking_budget(segment)`, which is narrower than the
    segment's window twice over: an action cue in the window means an embedded
    clip is already using it (Step 0), and the tail of what remains belongs to
    the pause the narrator must leave (Step 1). Targeting the raw window
    produces a track where every line fits and none of them breathe.

    A real translator predicts the spoken duration of each candidate with
    `model` and rephrases until it fits or the cap is hit; it must set
    `fitted=False` rather than return something too long silently.
    """

    name: str

    def translate(
        self, segment: Segment, *, target_language: str, model: RateModel
    ) -> TranslatedSegment: ...


@runtime_checkable
class TTSProvider(Protocol):
    """Turns translated text into an audio file on disk.

    Implementations write to `out_path` and report what they actually produced
    - duration is measured from the written file, never assumed, because the
    gap between predicted and actual duration is exactly what the QA report
    exists to surface.
    """

    name: str

    def synthesize(
        self, translated: TranslatedSegment, *, out_path: str, voice: str | None = None
    ) -> AudioAsset: ...


@runtime_checkable
class Aligner(Protocol):
    """Locates the speech inside a synthesised clip.

    Two implementations are registered. `clip-bounds` is the stub, and is
    right only for SilentTTS, whose clips are speech-shaped by construction.
    `vad` is real: it is Step 1's own detector, the same code that measured the
    client's delivered recordings, so a generated track and the client's
    baseline are measured on equal terms.

    Word-level alignment (WhisperX / MFA) is a third implementation and lands
    behind this same Protocol when per-word drift is needed.
    """

    name: str

    def align(self, audio: AudioAsset, text: str) -> AlignmentResult: ...


@runtime_checkable
class Exporter(Protocol):
    """Writes one deliverable for a finished track, returning the paths made."""

    name: str

    def export(self, track: LanguageTrack, out_dir: str) -> list[str]: ...
