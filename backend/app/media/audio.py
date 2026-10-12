"""Audio extraction.

ffmpeg is resolved from PATH first, then from the imageio-ffmpeg wheel, so the
project runs on a machine with no system ffmpeg installed (which is the normal
case on Windows).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import wave
from functools import lru_cache


@lru_cache(maxsize=1)
def ffmpeg_binary() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "ffmpeg not found on PATH and imageio-ffmpeg is not installed. "
            "Run: pip install imageio-ffmpeg"
        ) from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


def extract_audio(
    video_path: str,
    output_path: str,
    *,
    sample_rate: int = 16000,
    overwrite: bool = False,
) -> str:
    """Decode a video's audio track to mono PCM WAV.

    16 kHz mono is what the analysis stage wants: speech energy lives well below
    8 kHz, and mono avoids one channel's silence masking the other's speech.
    """
    if os.path.exists(output_path) and not overwrite:
        return output_path

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    result = subprocess.run(
        [
            ffmpeg_binary(), "-y", "-v", "error",
            "-i", video_path,
            "-vn", "-ac", "1", "-ar", str(sample_rate),
            "-c:a", "pcm_s16le",
            output_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {video_path}: {result.stderr.strip()}")
    return output_path


def wav_duration(path: str) -> float:
    """Duration of a WAV file in seconds, or 0.0 if it cannot be read.

    Read from the file rather than taken from whoever wrote it: QA compares
    predicted against actual, and that comparison is worthless if 'actual' is
    just the prediction handed back."""
    if not os.path.exists(path):
        return 0.0
    with contextlib.suppress(wave.Error, EOFError), wave.open(path, "rb") as handle:
        rate = handle.getframerate()
        return handle.getnframes() / rate if rate else 0.0
    return 0.0
