"""Providers by name.

HLD UC-07 requires switching the TTS provider at configuration level with no
change to project data or exports. That is only true if nothing constructs a
provider directly, so the runner and the CLI both come through here.

Registering a new provider is one line: real implementations (Piper, Sarvam,
WhisperX) land beside the stubs rather than replacing them, because a stub
that still runs is what keeps the pipeline demoable on any machine.
"""

from __future__ import annotations

from ..align.stub import ClipBoundsAligner
from ..export.manifest import ManifestExporter
from ..export.subtitles import SrtExporter
from ..translate.echo import EchoTranslator
from ..tts.silent import SilentTTS
from .interfaces import Aligner, Exporter, Translator, TTSProvider

TRANSLATORS: dict[str, type] = {
    "echo": EchoTranslator,
}

TTS_PROVIDERS: dict[str, type] = {
    "silent": SilentTTS,
}

ALIGNERS: dict[str, type] = {
    "clip-bounds": ClipBoundsAligner,
}

EXPORTERS: dict[str, type] = {
    "srt": SrtExporter,
    "manifest": ManifestExporter,
}


def _build(table: dict[str, type], name: str, kind: str):
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
