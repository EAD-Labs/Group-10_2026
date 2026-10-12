"""Providers by name.

HLD UC-07 requires switching the TTS provider at configuration level with no
change to project data or exports. That is only true if nothing constructs a
provider directly, so the runner, the CLI and the API all come through here.

Registering a new provider is one line: real implementations land beside the
stubs rather than replacing them, because a stub that still runs is what keeps
the pipeline demoable on any machine.

Factories take keyword options (`get_translator("groq", max_attempts=1)`), so
per-run settings travel with the run's config. They used to be module globals
the CLI mutated, which is fine for one process running one job and wrong for
an API running several.

Heavy providers (IndicTrans2 pulls in torch) are imported inside their factory,
so listing what is available never costs a model load.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from ..align.stub import ClipBoundsAligner
from ..align.vad import VadAligner
from ..export.manifest import ManifestExporter
from ..export.subtitles import SrtExporter
from ..translate.cache import TranslationCache
from ..translate.echo import EchoTranslator
from ..tts.silent import SilentTTS
from .interfaces import Aligner, Exporter, Translator, TTSProvider

DEFAULT_CACHE_PATH = os.path.join("out", "translation-cache.json")
"""Translations are cached on disk because the calls are metered: re-running a
track after correcting one segment must not re-pay for the other ninety-four."""


def _fitting(chat: str, with_mt: bool) -> Callable[..., Translator]:
    """A duration-fitting translator over the named chat model, optionally
    with IndicTrans2 drafting first so the LLM only edits what overruns."""

    def factory(**options: Any) -> Translator:
        from ..translate import llm
        from ..translate.fitting import FittingTranslator

        model = {"sarvam": llm.SarvamChat, "groq": llm.GroqChat}[chat]()
        cache = TranslationCache(options.pop("cache_path", DEFAULT_CACHE_PATH))
        drafter = None
        if with_mt:
            from ..translate.indictrans import IndicTransMT

            drafter = IndicTransMT(cache=cache)
        return FittingTranslator(model=model, drafter=drafter, cache=cache, **options)

    return factory


def _sarvam_tts(**options: Any) -> TTSProvider:
    from ..tts.sarvam import SarvamTTS

    return SarvamTTS(**options)


def _mixdown(**options: Any) -> Exporter:
    from ..export.mixdown import MixdownExporter

    return MixdownExporter(**options)


TRANSLATORS: dict[str, Callable[..., Translator]] = {
    # The stub: passes text through, so the pipeline runs with no provider.
    "echo": EchoTranslator,
    # The default real chain: IndicTrans2 drafts locally, sarvam-105b edits
    # only the drafts that overrun - one Sarvam key for this and the voice.
    "indictrans+sarvam": _fitting("sarvam", with_mt=True),
    # LLM only: the model translates and fits in one loop.
    "sarvam": _fitting("sarvam", with_mt=False),
    # The same two shapes on Groq's GPT-OSS 120B, kept for comparison.
    "indictrans+groq": _fitting("groq", with_mt=True),
    "groq": _fitting("groq", with_mt=False),
}

TTS_PROVIDERS: dict[str, Callable[..., TTSProvider]] = {
    "silent": SilentTTS,
    "sarvam": _sarvam_tts,
}

ALIGNERS: dict[str, Callable[..., Aligner]] = {
    # The stub, paired with SilentTTS: a silent clip has no speech to find.
    "clip-bounds": ClipBoundsAligner,
    # Real - Step 1's detector, the same one the client's delivered audio was
    # measured with. Use it with a real TTS provider.
    "vad": VadAligner,
}

EXPORTERS: dict[str, Callable[..., Exporter]] = {
    "srt": SrtExporter,
    "manifest": ManifestExporter,
    # The dubbed audio track, and the base video remuxed with it when known.
    "mixdown": _mixdown,
}


def _build(table: dict[str, Callable[..., Any]], name: str, kind: str, options: dict):
    try:
        factory = table[name]
    except KeyError:
        known = ", ".join(sorted(table))
        raise ValueError(f"unknown {kind} {name!r}; available: {known}") from None
    return factory(**options)


def get_translator(name: str = "echo", **options: Any) -> Translator:
    return _build(TRANSLATORS, name, "translator", options)


def get_tts(name: str = "silent", **options: Any) -> TTSProvider:
    return _build(TTS_PROVIDERS, name, "TTS provider", options)


def get_aligner(name: str = "clip-bounds", **options: Any) -> Aligner:
    return _build(ALIGNERS, name, "aligner", options)


def get_exporters(
    names: list[str] | None = None, options: dict[str, dict] | None = None
) -> list[Exporter]:
    options = options or {}
    return [
        _build(EXPORTERS, name, "exporter", options.get(name, {}))
        for name in (names or ["srt", "manifest"])
    ]


def is_stub(provider: object) -> bool:
    """Stubs say so themselves (`is_stub = True`), so every front end - CLI
    banner, API status, UI badge - reports the same answer."""
    return bool(getattr(provider, "is_stub", False))
