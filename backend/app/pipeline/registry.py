"""Providers by name.

HLD UC-07 requires switching the TTS provider at configuration level with no
change to project data or exports. That is only true if nothing constructs a
provider directly, so the runner and the CLI both come through here.

Registering a new provider is one line: real implementations (Piper, Sarvam,
WhisperX) land beside the stubs rather than replacing them, because a stub
that still runs is what keeps the pipeline demoable on any machine.
"""

from __future__ import annotations

from typing import Callable

from ..align.stub import ClipBoundsAligner
from ..align.vad import VadAligner
from ..export.manifest import ManifestExporter
from ..export.subtitles import SrtExporter
from ..translate.cache import TranslationCache
from ..translate.echo import EchoTranslator
from ..translate.fitting import FittingTranslator
from ..translate.llm import GroqChat
from ..tts.silent import SilentTTS
from .interfaces import Aligner, Exporter, Translator, TTSProvider

DEFAULT_CACHE_PATH = "out/translation-cache.json"
"""Translations are cached on disk because the calls are metered: re-running a
track after correcting one segment must not re-pay for the other ninety-four."""


DEFAULT_MAX_ATTEMPTS_OVERRIDE: int | None = None
"""Set by the CLI's --max-attempts. Retries cost metered calls, so the cap is
worth being able to lower for a cheap dry run."""


def _groq_translator() -> FittingTranslator:
    translator = FittingTranslator(
        model=GroqChat(), cache=TranslationCache(DEFAULT_CACHE_PATH)
    )
    if DEFAULT_MAX_ATTEMPTS_OVERRIDE is not None:
        translator.max_attempts = DEFAULT_MAX_ATTEMPTS_OVERRIDE
    return translator

TRANSLATORS: dict[str, Callable[[], Translator]] = {
    # The stub: passes text through, so the pipeline runs with no provider.
    "echo": EchoTranslator,
    # Module 2: GPT-OSS 120B on Groq, in the duration-fitting loop.
    "groq": _groq_translator,
}

TTS_PROVIDERS: dict[str, Callable[[], TTSProvider]] = {
    "silent": SilentTTS,
}

ALIGNERS: dict[str, Callable[[], Aligner]] = {
    # The stub, paired with SilentTTS: a silent clip has no speech to find.
    "clip-bounds": ClipBoundsAligner,
    # Real, and already built - Step 1's detector, the same one the client's
    # delivered audio was measured with. Use it with a real TTS provider.
    "vad": VadAligner,
}

EXPORTERS: dict[str, Callable[[], Exporter]] = {
    "srt": SrtExporter,
    "manifest": ManifestExporter,
}


def _build(table: dict[str, Callable[[], object]], name: str, kind: str):
    try:
        return table[name]()
    except KeyError:
        known = ", ".join(sorted(table))
        raise ValueError(f"unknown {kind} {name!r}; available: {known}") from None


def get_translator(name: str = "echo") -> Translator:
    return _build(TRANSLATORS, name, "translator")


def get_tts(name: str = "silent") -> TTSProvider:
    return _build(TTS_PROVIDERS, name, "TTS provider")


def get_aligner(name: str = "clip-bounds") -> Aligner:
    return _build(ALIGNERS, name, "aligner")


def get_exporters(names: list[str] | None = None) -> list[Exporter]:
    return [_build(EXPORTERS, name, "exporter") for name in (names or ["srt", "manifest"])]
