"""The job runner: parse -> translate -> synthesise -> align -> timeline -> QA
-> export.

This is the spine of the build plan. It runs today with every hard stage
faked, and each fake is replaced behind its Protocol without the runner
changing. What the runner owns is the ORDER, the artefact plumbing, and the
per-stage progress reporting - not the intelligence of any stage.

Re-running one segment (HLD UC-03: "only that segment is regenerated") is why
each stage is a separate function over a list rather than one loop doing all
six things per segment: `run_segments` takes the subset to redo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from ..duration.model import RateModel
from ..parsing.parser import parse_script
from ..schemas import (
    AlignmentResult,
    AudioAsset,
    LanguageTrack,
    ParsedScript,
    Segment,
    TranslatedSegment,
)
from ..timeline.builder import build_timeline
from ..timeline.qa import build_qa_report
from .interfaces import Aligner, Exporter, Translator, TTSProvider
from .registry import get_aligner, get_exporters, get_translator, get_tts

ProgressHook = Callable[[str, int, int], None]
"""stage name, completed, total - the hook the API's job-progress endpoint
will poll (HLD S10.2)."""


@dataclass
class PipelineConfig:
    language: str
    out_dir: str = "out"
    translator: str = "echo"
    tts: str = "silent"
    aligner: str = "clip-bounds"
    exporters: list[str] = field(default_factory=lambda: ["srt", "manifest"])
    voice: str | None = None
    rate_model: RateModel = field(default_factory=RateModel)


def _noop(stage: str, done: int, total: int) -> None:
    return None


def translate_segments(
    segments: list[Segment],
    translator: Translator,
    language: str,
    model: RateModel,
    progress: ProgressHook = _noop,
) -> list[TranslatedSegment]:
    out: list[TranslatedSegment] = []
    for index, segment in enumerate(segments, start=1):
        out.append(translator.translate(segment, target_language=language, model=model))
        progress("translate", index, len(segments))

    # Duck-typed so stubs need not implement it: a translator that paid for
    # these results gets the chance to persist them before the run moves on.
    flush = getattr(translator, "flush", None)
    if callable(flush):
        flush()
    return out


def synthesize_segments(
    translations: list[TranslatedSegment],
    tts: TTSProvider,
    audio_dir: str,
    voice: str | None = None,
    progress: ProgressHook = _noop,
) -> list[AudioAsset]:
    os.makedirs(audio_dir, exist_ok=True)
    out: list[AudioAsset] = []
    for index, translated in enumerate(translations, start=1):
        path = os.path.join(audio_dir, f"{translated.segment_id}.wav")
        out.append(tts.synthesize(translated, out_path=path, voice=voice))
        progress("synthesize", index, len(translations))
    return out


def align_segments(
    audio: list[AudioAsset],
    translations: list[TranslatedSegment],
    aligner: Aligner,
    progress: ProgressHook = _noop,
) -> list[AlignmentResult]:
    text_for = {t.segment_id: t.text for t in translations}
    out: list[AlignmentResult] = []
    for index, asset in enumerate(audio, start=1):
        out.append(aligner.align(asset, text_for.get(asset.segment_id, "")))
        progress("align", index, len(audio))
    return out


def run_track(
    script: ParsedScript,
    config: PipelineConfig,
    progress: ProgressHook = _noop,
) -> LanguageTrack:
    """Take a parsed script all the way to exported deliverables."""
    translator = get_translator(config.translator)
    tts = get_tts(config.tts)
    aligner = get_aligner(config.aligner)
    exporters: list[Exporter] = get_exporters(config.exporters)

    track_dir = os.path.join(config.out_dir, config.language)
    audio_dir = os.path.join(track_dir, "audio")

    translations = translate_segments(
        script.segments, translator, config.language, config.rate_model, progress
    )
    audio = synthesize_segments(translations, tts, audio_dir, config.voice, progress)
    alignments = align_segments(audio, translations, aligner, progress)

    timeline = build_timeline(script, audio, alignments)
    qa = build_qa_report(
        script, translations, audio, alignments, config.language, config.rate_model
    )

    track = LanguageTrack(
        source=script.source,
        language=config.language,
        duration=script.duration,
        translations=translations,
        audio=audio,
        alignments=alignments,
        timeline=timeline,
        qa=qa,
    )

    written: list[str] = []
    for index, exporter in enumerate(exporters, start=1):
        written.extend(exporter.export(track, track_dir))
        progress("export", index, len(exporters))
    track.exports = written
    return track


def run_pipeline(
    script_path: str,
    config: PipelineConfig,
    duration: float | None = None,
    source_language: str = "en",
    progress: ProgressHook = _noop,
) -> tuple[ParsedScript, LanguageTrack]:
    """Parse a script file, then run one language track over it."""
    script = parse_script(script_path, language=source_language, duration=duration)
    progress("parse", len(script.segments), len(script.segments))
    return script, run_track(script, config, progress)


def run_segments(
    script: ParsedScript,
    track: LanguageTrack,
    segment_ids: list[str],
    config: PipelineConfig,
    progress: ProgressHook = _noop,
) -> LanguageTrack:
    """Regenerate only the named segments and rebuild the derived artefacts.

    HLD UC-03 and the Language Reviewer's whole workflow: correcting one
    segment must not cost a full re-render. Timeline and QA are cheap to
    recompute, so they are rebuilt wholesale; translation and synthesis, which
    are the metered calls, run only for `segment_ids`.
    """
    wanted = set(segment_ids)
    segments = [s for s in script.segments if s.id in wanted]
    if not segments:
        return track

    translator = get_translator(config.translator)
    tts = get_tts(config.tts)
    aligner = get_aligner(config.aligner)

    track_dir = os.path.join(config.out_dir, config.language)
    audio_dir = os.path.join(track_dir, "audio")

    fresh_translations = translate_segments(
        segments, translator, config.language, config.rate_model, progress
    )
    fresh_audio = synthesize_segments(
        fresh_translations, tts, audio_dir, config.voice, progress
    )
    fresh_alignments = align_segments(fresh_audio, fresh_translations, aligner, progress)

    def replace(existing: list, updates: list) -> list:
        by_id = {item.segment_id: item for item in existing}
        for item in updates:
            by_id[item.segment_id] = item
        order = {s.id: i for i, s in enumerate(script.segments)}
        return sorted(by_id.values(), key=lambda item: order.get(item.segment_id, 0))

    track.translations = replace(track.translations, fresh_translations)
    track.audio = replace(track.audio, fresh_audio)
    track.alignments = replace(track.alignments, fresh_alignments)
    track.timeline = build_timeline(script, track.audio, track.alignments)
    track.qa = build_qa_report(
        script,
        track.translations,
        track.audio,
        track.alignments,
        config.language,
        config.rate_model,
    )

    written: list[str] = []
    for exporter in get_exporters(config.exporters):
        written.extend(exporter.export(track, track_dir))
    track.exports = written
    return track
