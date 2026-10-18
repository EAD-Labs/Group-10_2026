"""SarvamTTS - narration from Sarvam AI's Bulbul voices.

    POST https://api.sarvam.ai/text-to-speech
    header  api-subscription-key: <SARVAM_API_KEY>
    body    {text, language_code: "ta-IN", model, speaker, pace, speech_sample_rate, ...}
    reply   {"request_id": ..., "audios": ["<base64 WAV>"]}

Three things it does beyond the call itself.

The clip's duration is MEASURED from the decoded audio, never assumed. The gap
between what the duration model predicted and what the voice actually took is
exactly what the QA report and the pace-correction step exist to act on.

It speaks at a base `pace` chosen for the whole track (1.0 is the voice's
natural speed; slower is calmer and leaves less room for text), and accepts a
per-clip `pace` so the runner can re-request an overrunning clip slightly
faster - within +10% of the base - before deciding the text has to change.

Clips are cached on disk by everything that would change the audio, so a
re-run, or a reviewer fixing one segment, never re-pays for the other ninety-four.

bulbul:v3 is the default: Sarvam has deprecated v2 (requests now fail with
"Model 'bulbul:v2' has been deprecated"). v3 has no `enable_preprocessing`, so
numerals are read as the model sees fit; v2's option is still sent if
SARVAM_TTS_MODEL selects a model that accepts it.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import shutil

from ..config import settings
from ..http import ProviderError, post_with_retry
from ..schemas import AudioAsset, TranslatedSegment
from .silent import write_silence

SARVAM_TTS_ENDPOINT = "https://api.sarvam.ai/text-to-speech"

LANGUAGE_CODES = {
    "en": "en-IN",
    "ta": "ta-IN",
    "hi": "hi-IN",
    "mr": "mr-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "bn": "bn-IN",
    "gu": "gu-IN",
    "pa": "pa-IN",
    "or": "od-IN",
}

MALE_VOICES = (
    "shubh", "aditya", "rahul", "rohan", "amit", "dev", "ratan", "varun", "manan",
    "sumit", "kabir", "aayan", "ashutosh", "advait", "anand", "tarun", "sunny",
    "mani", "gokul", "vijay", "mohit", "rehan", "soham",
)
FEMALE_VOICES = (
    "ritu", "priya", "neha", "pooja", "simran", "kavya", "ishita", "shreya",
    "roopa", "tanya", "shruti", "suhani", "kavitha", "rupali",
)
"""Bulbul v3's 37 speakers, as Sarvam's voices guide groups them. Any of them
speaks every language."""

FEATURED_VOICES = ("shubh", "ishita", "priya", "mani", "aditya", "ritu")
"""Sarvam's recommended starting points: shubh and ishita are its all-language
defaults; priya (female) and mani (male) are its best-rated picks in several
languages. `varun` is left out on purpose - Sarvam reserves it for drama."""


def voices() -> list[dict]:
    """Every v3 speaker with its gender, featured voices first."""
    gender = {name: "male" for name in MALE_VOICES} | {name: "female" for name in FEMALE_VOICES}
    order = list(FEATURED_VOICES) + sorted(n for n in gender if n not in FEATURED_VOICES)
    return [{"id": n, "gender": gender[n], "featured": n in FEATURED_VOICES} for n in order]


PACE_LIMITS = {"bulbul:v2": (0.3, 3.0)}
DEFAULT_PACE_LIMITS = (0.5, 2.0)
MAX_CHARS = {"bulbul:v2": 1500}
DEFAULT_MAX_CHARS = 2500

SAMPLE_RATE = 22050
DEFAULT_CACHE_DIR = os.path.join("out", "tts-cache")


class TTSError(ProviderError):
    """Sarvam could not be reached, refused the request, or returned no audio."""


class SarvamTTS:
    """Bulbul text-to-speech over Sarvam's REST API."""

    supports_pace = True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        speaker: str | None = None,
        sample_rate: int = SAMPLE_RATE,
        cache_dir: str | None = DEFAULT_CACHE_DIR,
        timeout: float = 60.0,
        max_retries: int = 8,
        preprocess: bool = True,
        pace: float = 1.0,
    ) -> None:
        config = settings()
        self._api_key = api_key if api_key is not None else config.sarvam_api_key
        self.model = model or config.sarvam_tts_model
        self.speaker = speaker or config.sarvam_speaker
        self.sample_rate = sample_rate
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.max_retries = max_retries
        self.preprocess = preprocess
        self.pace = pace
        self.name = f"sarvam:{self.model}"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    # -- request -------------------------------------------------------------

    def _payload(self, text: str, language: str, speaker: str, pace: float) -> dict:
        try:
            language_code = LANGUAGE_CODES[language]
        except KeyError:
            raise TTSError(f"Sarvam has no voice for language {language!r}") from None
        low, high = PACE_LIMITS.get(self.model, DEFAULT_PACE_LIMITS)
        payload = {
            "text": text,
            "language_code": language_code,
            "model": self.model,
            "speaker": speaker,
            "pace": round(min(max(pace, low), high), 3),
            "speech_sample_rate": self.sample_rate,
        }
        if self.model == "bulbul:v2":
            payload["enable_preprocessing"] = self.preprocess
        return payload

    def _cache_path(self, payload: dict) -> str | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(
            repr(sorted(payload.items())).encode("utf-8")
        ).hexdigest()[:32]
        return os.path.join(self.cache_dir, f"{digest}.wav")

    def _request(self, payload: dict) -> bytes:
        if not self._api_key:
            raise TTSError(
                "SARVAM_API_KEY is not set. Put it in the environment or in a .env "
                "file at the repository root (see .env.example). Never commit it."
            )

        def parse(response) -> bytes:
            try:
                audios = response.json()["audios"]
                return base64.b64decode(audios[0])
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise TTSError(f"unexpected Sarvam response: {response.text[:300]}") from exc

        return post_with_retry(
            SARVAM_TTS_ENDPOINT,
            payload,
            headers={"api-subscription-key": self._api_key},
            parse=parse,
            label=self.name,
            timeout=self.timeout,
            max_retries=self.max_retries,
            error=TTSError,
        )

    # -- the TTSProvider protocol ---------------------------------------------

    def synthesize(
        self,
        translated: TranslatedSegment,
        *,
        out_path: str,
        voice: str | None = None,
        pace: float | None = None,
    ) -> AudioAsset:
        speaker = voice or self.speaker
        pace = self.pace if pace is None else pace
        text = translated.text.strip()
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

        if not text:
            # A failed translation: there is nothing to say, and paying for
            # silence would hide that. The QA report shows the empty clip.
            duration = write_silence(out_path, 0.0, self.sample_rate)
            return self._asset(translated, out_path, duration, speaker)

        limit = MAX_CHARS.get(self.model, DEFAULT_MAX_CHARS)
        if len(text) > limit:
            raise TTSError(
                f"{translated.segment_id}: {len(text)} characters exceeds {self.model}'s "
                f"{limit}-character limit"
            )

        payload = self._payload(text, translated.language, speaker, pace)
        cached = self._cache_path(payload)
        if cached and os.path.exists(cached):
            shutil.copyfile(cached, out_path)
        else:
            audio = self._request(payload)
            _write_pcm_wav(audio, out_path)
            if cached:
                os.makedirs(self.cache_dir, exist_ok=True)
                shutil.copyfile(out_path, cached)

        return self._asset(translated, out_path, _measure(out_path), speaker)

    def _asset(
        self, translated: TranslatedSegment, path: str, duration: float, speaker: str
    ) -> AudioAsset:
        return AudioAsset(
            segment_id=translated.segment_id,
            language=translated.language,
            path=path,
            duration=duration,
            sample_rate=self.sample_rate,
            provider=self.name,
            voice=speaker,
        )


def _write_pcm_wav(audio: bytes, path: str) -> None:
    """Normalise whatever WAV variant came back to plain 16-bit PCM.

    Streaming encoders sometimes leave the RIFF size fields unset, which the
    stdlib `wave` reader - used by the aligners and the mixdown - rejects or
    misreads. Decoding and re-writing once here means every later stage reads
    an ordinary file."""
    import soundfile as sf

    data, rate = sf.read(io.BytesIO(audio), dtype="int16", always_2d=False)
    if getattr(data, "ndim", 1) > 1:
        data = data.mean(axis=1).astype("int16")
    sf.write(path, data, rate, subtype="PCM_16")


def _measure(path: str) -> float:
    import soundfile as sf

    info = sf.info(path)
    return info.frames / info.samplerate if info.samplerate else 0.0
