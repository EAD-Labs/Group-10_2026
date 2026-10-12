"""Configuration and secrets, in one place.

Several providers need credentials now (Groq for shortening, Sarvam for
speech) and the API needs to know where to put jobs. Each used to read the
environment itself; they read `settings()` instead, so there is one answer to
"where does this key come from" and one place to change it.

Secrets stay out of source control (HLD S10.5): they come from the environment
or from a .env file at the repository root, which is gitignored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def find_dotenv(filename: str = ".env") -> str | None:
    """Locate .env at the working directory or any parent.

    The file lives at the repository root but commands are run from backend/,
    so looking only in the working directory finds nothing and the failure
    reads as a missing key rather than a missing file.
    """
    directory = os.path.abspath(os.getcwd())
    while True:
        candidate = os.path.join(directory, filename)
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def load_dotenv(path: str | None = None) -> None:
    """Read KEY=VALUE lines into the environment if the file exists.

    Existing environment variables win, so a real deployment's injected
    secrets are never overwritten by a stray file.
    """
    path = path or find_dotenv()
    if not path or not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = ""
    sarvam_api_key: str = ""
    indictrans_model: str = "ai4bharat/indictrans2-en-indic-dist-200M"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_speaker: str = "shubh"
    sarvam_llm_model: str = "sarvam-105b"
    out_dir: str = "out"


@lru_cache(maxsize=1)
def settings() -> Settings:
    """Read once per process. Tests that need a different value construct
    `Settings` directly rather than mutating the environment."""
    load_dotenv()
    env = os.environ.get
    defaults = Settings()
    return Settings(
        groq_api_key=env("GROQ_API_KEY", ""),
        sarvam_api_key=env("SARVAM_API_KEY", ""),
        indictrans_model=env("INDICTRANS_MODEL", defaults.indictrans_model),
        sarvam_tts_model=env("SARVAM_TTS_MODEL", defaults.sarvam_tts_model),
        sarvam_speaker=env("SARVAM_SPEAKER", defaults.sarvam_speaker),
        sarvam_llm_model=env("SARVAM_LLM_MODEL", defaults.sarvam_llm_model),
        out_dir=env("DUB_OUT_DIR", defaults.out_dir),
    )
