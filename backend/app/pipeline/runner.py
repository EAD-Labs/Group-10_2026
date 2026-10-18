"""The job runner: parse -> translate -> synthesise -> align -> fit audio ->
timeline -> QA -> export.

What the runner owns is the ORDER, the artefact plumbing, and the per-stage
progress reporting - not the intelligence of any stage. Each stage is a
provider behind a Protocol, resolved by name, so a stub and the real thing are
interchangeable without the runner changing.

Re-running one segment (HLD UC-03: "only that segment is regenerated") is why
each stage is a separate function over a list rather than one loop doing
everything per segment: `run_segments` takes the subset to redo.
"""

from __future__ import annotations

import inspect
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Sequence, TypeVar

from ..duration.calibrate import calibrate, calibrated_rate
from ..duration.model import (
    DRIFT_TOLERANCE,
    RATE_TOLERANCE,
    VOICE_RATES_PATH,
    RateModel,
    voice_key,
)
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
from . import store
from .interfaces import Aligner, Exporter, Translator, TTSProvider
from .registry import get_aligner, get_exporters, get_translator, get_tts, is_stub

ProgressHook = Callable[..., None]
"""(stage name, completed, total[, item]) - the hook the API's job-progress
endpoint polls (HLD S10.2). A hook that takes a fourth argument also receives
each finished result - a TranslatedSegment, an AudioAsset - which is what the
page's live feed shows. Three-argument hooks keep working."""

STAGES = ("parse", "calibrate", "translate", "synthesize", "align", "fit_audio", "export")

T = TypeVar("T")
R = TypeVar("R")


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
    provider_options: dict[str, dict] = field(default_factory=dict)
    """Keyword options per provider, keyed "translator", "tts", "aligner" or an
    exporter's name - e.g. {"translator": {"max_attempts": 1}}."""
    max_workers: int = 1
    """Concurrent calls in the metered stages. Translation and synthesis are
    network-bound, so 4-8 cuts a run's wall time several-fold; 1 keeps runs
    deterministic for tests."""
    video_path: str | None = None
    """The base video, when known - the mixdown exporter muxes the dub into it
    and lifts the embedded clips' original audio from it."""
    voice_pace: float = 1.0
    """The speaking pace for the whole track, for TTS providers that take one
    (1.0 = the voice's natural speed). Slower is calmer and leaves less time
    per line, so more text is shortened to fit."""
    use_voice_rates: bool = True
    """Budget at the TTS voice's calibrated rate (app.calibrate_voice) when one
    has been measured, rather than the human narrator's."""

    @property
    def track_dir(self) -> str:
        return os.path.join(self.out_dir, self.language)

    @property
    def audio_dir(self) -> str:
        return os.path.join(self.track_dir, "audio")


@dataclass
class Providers:
    translator: Translator
    tts: TTSProvider
    aligner: Aligner
    exporters: list[Exporter]

    @property
    def stubs(self) -> list[str]:
        """Names of the stages still faked - every front end reports these, so
        no demo leaves anyone unsure which numbers are real. Exporters are left
        out: the manifest is a stand-in for a later project format and changes
        nothing that is heard or measured."""
        every = [self.translator, self.tts, self.aligner]
        return sorted({p.name for p in every if is_stub(p)})


def build_providers(config: PipelineConfig, script: ParsedScript | None = None) -> Providers:
    options = config.provider_options
    exporter_options = {name: dict(options.get(name, {})) for name in config.exporters}
    if "mixdown" in exporter_options and script is not None:
        exporter_options["mixdown"].setdefault("script", script)
        exporter_options["mixdown"].setdefault("video_path", config.video_path)
    providers = Providers(
        translator=get_translator(config.translator, **options.get("translator", {})),
        tts=get_tts(config.tts, **options.get("tts", {})),
        aligner=get_aligner(config.aligner, **options.get("aligner", {})),
        exporters=get_exporters(config.exporters, exporter_options),
    )
    if getattr(providers.tts, "supports_pace", False):
        providers.tts.pace = config.voice_pace
    if config.use_voice_rates and not is_stub(providers.tts):
        config.rate_model = RateModel.for_voice(_voice_key(config, providers.tts))
    return providers


def _speaker(config: PipelineConfig, tts: TTSProvider) -> str | None:
    return config.voice or getattr(tts, "speaker", None)


def _voice_key(config: PipelineConfig, tts: TTSProvider) -> str:
    """Where this track's voice - provider, speaker, pace - keeps its rate."""
    return voice_key(tts.name, _speaker(config, tts), getattr(tts, "pace", 1.0))


def _noop(stage: str, done: int, total: int, item=None) -> None:
    return None


def _adapt(progress: ProgressHook) -> ProgressHook:
    """Accept both hook shapes: pass the item only to hooks that want it."""
    if progress is _noop:
        return progress
    try:
        params = inspect.signature(progress).parameters.values()
    except (TypeError, ValueError):
        return progress
    takes_item = any(p.kind is p.VAR_POSITIONAL for p in params) or len(
        [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    ) >= 4
    if takes_item:
        return progress
    return lambda stage, done, total, item=None: progress(stage, done, total)


def _map(
    fn: Callable[[T], R],
    items: Sequence[T],
    stage: str,
    progress: ProgressHook,
    max_workers: int = 1,
) -> list[R]:
    """Apply `fn` to every item, in order, reporting progress as each finishes.

    Results keep the input order whatever order the calls complete in - the
    rest of the pipeline matches artefacts by position as well as by id."""
    total = len(items)
    if max_workers <= 1 or total <= 1:
        out = []
        for index, item in enumerate(items, start=1):
            out.append(fn(item))
            progress(stage, index, total, out[-1])
        return out

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(fn, item) for item in items]
        results: list[R] = []
        for index, future in enumerate(futures, start=1):
            results.append(future.result())
            progress(stage, index, total, results[-1])
        return results


def ensure_voice_rate(
    script: ParsedScript,
    config: PipelineConfig,
    providers: Providers,
    progress: ProgressHook = _noop,
    rates_path: str | None = None,
) -> float | None:
    """Measure the voice first if this language, speaker and pace never were.

    Budgeting at a rate the voice does not speak at makes "fits on paper" and
    "fits in the audio" disagree, and the fallback rate is the human English
    narrator's. So a new language, voice or pace is calibrated on ~20 lines of
    THIS script's own MT drafts before translation starts - the drafts are
    needed by the translate stage anyway, so the cost is ~20 TTS calls, once.
    """
    path = rates_path or VOICE_RATES_PATH
    tts = providers.tts
    if not config.use_voice_rates or is_stub(tts):
        return None
    speaker = _speaker(config, tts)
    key = _voice_key(config, tts)
    known = calibrated_rate(key, config.language, path)
    if known:
        return known
    drafter = getattr(providers.translator, "drafter", None)
    if drafter is None or is_stub(providers.aligner):
        return None  # nothing to make target-language text with, or to measure it

    class _Voice:
        """The track's TTS, pinned to the track's speaker."""

        def synthesize(self, translated, *, out_path):
            return tts.synthesize(translated, out_path=out_path, voice=speaker)

    progress("calibrate", 0, 1)
    rate = calibrate(
        script.segments,
        config.language,
        _Voice(),
        providers.aligner,
        drafter,
        key=key,
        out_dir=os.path.join(config.track_dir, "calibration"),
        rates_path=path,
        progress=lambda done, total: progress("calibrate", done, total),
    )
    if rate:
        config.rate_model = RateModel.for_voice(key, path)
    return rate


def translate_segments(
    segments: list[Segment],
    translator: Translator,
    language: str,
    model: RateModel,
    progress: ProgressHook = _noop,
    max_workers: int = 1,
) -> list[TranslatedSegment]:
    # Duck-typed, like flush below: a translator with a local MT model drafts
    # the whole track in batches first, which is far faster on CPU.
    prepare = getattr(translator, "prepare", None)
    if callable(prepare):
        progress("translate", 0, len(segments))
        prepare(segments, language)

    out = _map(
        lambda segment: translator.translate(segment, target_language=language, model=model),
        segments,
        "translate",
        progress,
        max_workers,
    )
    # Duck-typed so stubs need not implement it: a translator that paid for
    # these results gets the chance to persist them before the run moves on.
    flush = getattr(translator, "flush", None)
    if callable(flush):
        flush()
    return out


def _clip_path(audio_dir: str, segment_id: str) -> str:
    return os.path.join(audio_dir, f"{segment_id}.wav")


def synthesize_segments(
    translations: list[TranslatedSegment],
    tts: TTSProvider,
    audio_dir: str,
    voice: str | None = None,
    progress: ProgressHook = _noop,
    max_workers: int = 1,
) -> list[AudioAsset]:
    os.makedirs(audio_dir, exist_ok=True)
    return _map(
        lambda t: tts.synthesize(t, out_path=_clip_path(audio_dir, t.segment_id), voice=voice),
        translations,
        "synthesize",
        progress,
        max_workers,
    )


def align_segments(
    audio: list[AudioAsset],
    translations: list[TranslatedSegment],
    aligner: Aligner,
    progress: ProgressHook = _noop,
) -> list[AlignmentResult]:
    text_for = {t.segment_id: t.text for t in translations}
    return _map(
        lambda asset: aligner.align(asset, text_for.get(asset.segment_id, "")),
        audio,
        "align",
        progress,
    )


def pace_for(actual: float, budget: float) -> float:
    """The speed-up that would land `actual` seconds of speech in `budget`,
    clamped to the HLD's +/-10% rate tolerance - beyond that the delivery is
    rushed, and the fix belongs in the text, not the voice."""
    if budget <= 0 or actual <= budget:
        return 1.0
    return min(actual / budget, 1.0 + RATE_TOLERANCE)


def fit_audio(
    translations: list[TranslatedSegment],
    audio: list[AudioAsset],
    alignments: list[AlignmentResult],
    providers: Providers,
    config: PipelineConfig,
    progress: ProgressHook = _noop,
) -> tuple[list[AudioAsset], list[AlignmentResult]]:
    """Re-synthesise overrunning clips slightly faster, once.

    The duration model predicts from text; the voice decides. A clip whose
    measured speech overruns its speaking budget by more than the drift
    tolerance is re-requested at the pace that would fit, capped at +10% of the
    track's base pace (an 0.8 track is corrected to at most 0.88). What
    still overruns after that is reported, not hidden: it needs shorter text.

    Only providers that declare `supports_pace` take part; a stub's clip is
    its prediction, so there is nothing to correct.
    """
    base = getattr(providers.tts, "pace", 1.0)
    if not getattr(providers.tts, "supports_pace", False):
        progress("fit_audio", 1, 1)
        return audio, alignments

    by_alignment = {a.segment_id: a for a in alignments}
    by_audio = {a.segment_id: a for a in audio}
    overrunning = [
        t
        for t in translations
        if t.segment_id in by_alignment
        and by_alignment[t.segment_id].speech_duration - t.budget > DRIFT_TOLERANCE
    ]

    def redo(translated: TranslatedSegment) -> tuple[AudioAsset, AlignmentResult]:
        actual = by_alignment[translated.segment_id].speech_duration
        pace = base * pace_for(actual, translated.budget)
        asset = providers.tts.synthesize(
            translated,
            out_path=_clip_path(config.audio_dir, translated.segment_id),
            voice=config.voice,
            pace=pace,
        )
        aligned = providers.aligner.align(asset, translated.text)
        if aligned.speech_duration - translated.budget > DRIFT_TOLERANCE:
            translated.note = (
                (translated.note + "; " if translated.note else "")
                + f"audio still {aligned.speech_duration - translated.budget:.2f}s over "
                f"at pace {pace:.2f} - shorten the text"
            )
        return asset, aligned

    for asset, aligned in _map(redo, overrunning, "fit_audio", progress, config.max_workers):
        by_audio[asset.segment_id] = asset
        by_alignment[aligned.segment_id] = aligned
    if not overrunning:
        progress("fit_audio", 1, 1)

    # The measurement outranks the prediction. A line the duration model
    # called too long but the voice actually said inside its budget does not
    # need an author: on the first real Sarvam run, all four "escalated"
    # segments measured 0.04-0.62 s UNDER budget, pauses intact.
    for translated in translations:
        aligned = by_alignment.get(translated.segment_id)
        if translated.fitted or not translated.text or aligned is None:
            continue
        drift = aligned.speech_duration - translated.budget
        if drift <= DRIFT_TOLERANCE:
            translated.fitted = True
            translated.stage = "draft" if translated.text == translated.draft_text else "shortened"
            translated.note = (
                f"predicted {translated.overrun:+.2f}s over, but the audio fits "
                f"({drift:+.2f}s)"
            )

    return (
        [by_audio[a.segment_id] for a in audio],
        [by_alignment[a.segment_id] for a in alignments],
    )


def _finalize(
    script: ParsedScript,
    track: LanguageTrack,
    config: PipelineConfig,
    exporters: list[Exporter],
    progress: ProgressHook = _noop,
) -> LanguageTrack:
    """Rebuild everything derived - timeline, QA, deliverables - and persist.

    Cheap relative to translation and synthesis, so always done wholesale; a
    one-segment fix still gets a consistent timeline and an honest report."""
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
    for index, exporter in enumerate(exporters, start=1):
        written.extend(exporter.export(track, config.track_dir))
        progress("export", index, len(exporters))
    track.exports = written

    store.save(config.track_dir, script, track, config)
    return track


def _render(
    script: ParsedScript,
    segments: list[Segment],
    config: PipelineConfig,
    providers: Providers,
    progress: ProgressHook,
) -> tuple[list[TranslatedSegment], list[AudioAsset], list[AlignmentResult]]:
    """The metered half of the pipeline, over whichever segments need it."""
    translations = translate_segments(
        segments,
        providers.translator,
        config.language,
        config.rate_model,
        progress,
        config.max_workers,
    )
    audio = synthesize_segments(
        translations, providers.tts, config.audio_dir, config.voice, progress, config.max_workers
    )
    alignments = align_segments(audio, translations, providers.aligner, progress)
    audio, alignments = fit_audio(translations, audio, alignments, providers, config, progress)
    return translations, audio, alignments


def run_track(
    script: ParsedScript,
    config: PipelineConfig,
    progress: ProgressHook = _noop,
    providers: Providers | None = None,
) -> LanguageTrack:
    """Take a parsed script all the way to exported deliverables."""
    progress = _adapt(progress)
    providers = providers or build_providers(config, script)
    ensure_voice_rate(script, config, providers, progress)
    translations, audio, alignments = _render(
        script, script.segments, config, providers, progress
    )
    track = LanguageTrack(
        source=script.source,
        language=config.language,
        duration=script.duration,
        translations=translations,
        audio=audio,
        alignments=alignments,
    )
    return _finalize(script, track, config, providers.exporters, progress)


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
    providers: Providers | None = None,
) -> LanguageTrack:
    """Regenerate only the named segments and rebuild the derived artefacts.

    HLD UC-03 and the Language Reviewer's whole workflow: correcting one
    segment must not cost a full re-render. Translation and synthesis, the
    metered calls, run only for `segment_ids`.
    """
    progress = _adapt(progress)
    wanted = set(segment_ids)
    segments = [s for s in script.segments if s.id in wanted]
    if not segments:
        return track

    providers = providers or build_providers(config, script)
    translations, audio, alignments = _render(script, segments, config, providers, progress)

    order = {s.id: i for i, s in enumerate(script.segments)}

    def replace(existing: list, updates: list) -> list:
        by_id = {item.segment_id: item for item in existing}
        by_id.update({item.segment_id: item for item in updates})
        return sorted(by_id.values(), key=lambda item: order.get(item.segment_id, len(order)))

    track.translations = replace(track.translations, translations)
    track.audio = replace(track.audio, audio)
    track.alignments = replace(track.alignments, alignments)
    return _finalize(script, track, config, providers.exporters, progress)
