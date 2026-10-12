"""MixdownExporter - the dubbed audio track, and the video to watch it on.

Every other exporter hands an editor parts. This one assembles them, so the
pipeline's output can be judged the way a learner will meet it: by watching.

    silence the length of the base video
      + each narration clip at its timeline start, lead-in trimmed
      + the embedded clips' audio, lifted from the base video at their cues
    -> <lang>-dub.wav
    -> <lang>-dub.webm / .mp4   (base video's picture, dubbed audio)

The embedded clips are taken from the base video because that is where the
English edition already has them spliced. A Tamil release would splice the
Tamil edition of each source tutorial instead; until those are supplied, the
original keeps the cue windows from going silent.

Overrunning narration is mixed, not truncated: a line that runs into the next
is audible as exactly that, which is what the QA report says it is.
"""

from __future__ import annotations

import os
import subprocess

import numpy as np

from ..media.audio import extract_audio, ffmpeg_binary
from ..schemas import LanguageTrack, ParsedScript

SAMPLE_RATE = 22050


def _read_mono(path: str, sample_rate: int) -> np.ndarray:
    import soundfile as sf

    data, rate = sf.read(path, dtype="float32", always_2d=True)
    data = data.mean(axis=1)
    if rate != sample_rate and len(data):
        # Linear resampling is ample for speech placed on a timeline; the
        # providers in use all emit 22.05 kHz, so this is the rare path.
        positions = np.arange(int(len(data) * sample_rate / rate)) * rate / sample_rate
        data = np.interp(positions, np.arange(len(data)), data).astype("float32")
    return data


def _place(buffer: np.ndarray, clip: np.ndarray, at: int, *, replace: bool = False) -> None:
    if at >= len(buffer) or not len(clip):
        return
    at = max(at, 0)
    clip = clip[: len(buffer) - at]
    if replace:
        buffer[at : at + len(clip)] = clip
    else:
        buffer[at : at + len(clip)] += clip


def mix(
    track: LanguageTrack,
    script: ParsedScript | None = None,
    base_audio: str | None = None,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """The dubbed track as samples. Separate from writing so it can be tested."""
    buffer = np.zeros(int(round(track.duration * sample_rate)), dtype="float32")

    if base_audio and script is not None and script.cues:
        original = _read_mono(base_audio, sample_rate)
        for cue in script.cues:
            if cue.clip_duration <= 0:
                continue
            start = int(round(cue.at * sample_rate))
            end = start + int(round(cue.clip_duration * sample_rate))
            _place(buffer, original[start:end], start, replace=True)

    for item in track.timeline:
        if not item.audio_path or not os.path.exists(item.audio_path):
            continue
        clip = _read_mono(item.audio_path, sample_rate)
        clip = clip[int(round(item.audio_offset * sample_rate)) :]
        _place(buffer, clip, int(round(item.start * sample_rate)))

    np.clip(buffer, -1.0, 1.0, out=buffer)
    return buffer


class MixdownExporter:
    name = "mixdown"

    def __init__(
        self,
        script: ParsedScript | None = None,
        video_path: str | None = None,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self.script = script
        self.video_path = video_path
        self.sample_rate = sample_rate

    def export(self, track: LanguageTrack, out_dir: str) -> list[str]:
        import soundfile as sf

        os.makedirs(out_dir, exist_ok=True)
        base_audio = None
        if self.video_path and os.path.exists(self.video_path):
            base_audio = extract_audio(
                self.video_path,
                os.path.join(out_dir, "base-audio.wav"),
                sample_rate=self.sample_rate,
            )

        wav_path = os.path.join(out_dir, f"{track.language}-dub.wav")
        sf.write(
            wav_path,
            mix(track, self.script, base_audio, self.sample_rate),
            self.sample_rate,
            subtype="PCM_16",
        )
        written = [wav_path]

        if self.video_path and os.path.exists(self.video_path):
            video = mux(self.video_path, wav_path, out_dir, track.language)
            if video:
                written.append(video)
        return written


def mux(video_path: str, audio_path: str, out_dir: str, language: str) -> str | None:
    """Swap the base video's audio for the dub, copying the picture untouched.

    WebM/Matroska sources stay WebM (Opus audio); anything else becomes MP4
    (AAC). Returns None, not an exception, if ffmpeg cannot do it - the dubbed
    WAV is the deliverable; the video is a convenience for review."""
    webm = os.path.splitext(video_path)[1].lower() in {".webm", ".mkv"}
    out_path = os.path.join(out_dir, f"{language}-dub.{'webm' if webm else 'mp4'}")
    result = subprocess.run(
        [
            ffmpeg_binary(), "-y", "-v", "error",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "libopus" if webm else "aac",
            "-b:a", "96k",
            # No -shortest: the dub is exactly the container's length, and a
            # source whose video stream ends early (the Synfig English one, by
            # 2.7 s) would otherwise cut the last lines of narration.
            out_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  mixdown: could not mux video ({result.stderr.strip()[:200]})")
        return None
    return out_path
