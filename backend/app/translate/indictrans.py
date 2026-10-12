"""IndicTransMT - the local first draft, from AI4Bharat's IndicTrans2.

The fitting loop used to ask a metered LLM for every segment, then ask again
for every segment that came back too long. Most of that first round is plain
translation, which a small open model does well and for free. So IndicTrans2
drafts every segment locally, and the LLM is called only for the drafts that
overrun their budget or lose an on-screen term - the editing job it is
actually needed for.

The distilled 200M English->Indic checkpoint runs on CPU at a few seconds per
batch. It is downloaded from Hugging Face on first use (accept the model's
licence there and `huggingface-cli login` once if it is gated), loaded once
per process, and its outputs are cached on disk like every other paid-for
answer - here paid for in CPU time.

Needs the optional requirements: pip install -r requirements-mt.txt
"""

from __future__ import annotations

import hashlib
import threading
from typing import Iterable

from ..config import settings
from ..schemas import Segment
from .cache import TranslationCache
from .terms import fix_punctuation, glossary, protect, restore

FLORES_CODES = {
    "en": "eng_Latn",
    "ta": "tam_Taml",
    "hi": "hin_Deva",
    "mr": "mar_Deva",
    "te": "tel_Telu",
    "kn": "kan_Knda",
    "ml": "mal_Mlym",
    "bn": "ben_Beng",
    "gu": "guj_Gujr",
    "pa": "pan_Guru",
    "or": "ory_Orya",
}
"""IndicTrans2 names languages by FLORES-200 code, script included."""

BATCH_SIZE = 8
NUM_BEAMS = 2
"""Beam search width. 5 is the model card's choice for best BLEU; 2 is several
times faster on CPU and the loss hardly matters here, since every draft that
overruns is edited by the LLM anyway."""
MAX_LENGTH = 256
PROTECTION_VERSION = 2
"""Bumped when terms.py changes what gets protected - part of the cache key,
because the cached output is the model's answer to the PROTECTED text."""


class MTUnavailable(RuntimeError):
    """The model or its dependencies could not be loaded."""


class IndicTransMT:
    """English -> Indic machine translation with IndicTrans2, on CPU."""

    _lock = threading.Lock()
    _loaded: dict[str, tuple] = {}
    """One model per process, shared across instances and jobs - loading it is
    the slow part, and the API constructs a translator per job."""

    def __init__(
        self,
        model_name: str | None = None,
        *,
        cache: TranslationCache | None = None,
        device: str = "cpu",
        source_language: str = "en",
    ) -> None:
        self.model_name = model_name or settings().indictrans_model
        self.name = f"indictrans2:{self.model_name.rsplit('/', 1)[-1]}"
        self.cache = cache or TranslationCache()
        self.device = device
        self.source_language = source_language
        self.glossary: list[str] = []
        """The script's on-screen terms, built by `prepare`; protected in
        every segment, not only the ones that bold them."""

    # -- loading -------------------------------------------------------------

    def _load(self):
        with self._lock:
            if self.model_name in self._loaded:
                return self._loaded[self.model_name]
            try:
                import torch  # noqa: F401
                from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            except ImportError as exc:
                raise MTUnavailable(
                    "IndicTrans2 needs torch and transformers: "
                    "pip install -r requirements-mt.txt"
                ) from exc
            try:
                from IndicTransToolkit.processor import IndicProcessor
            except ImportError:
                try:
                    from IndicTransToolkit import IndicProcessor  # older releases
                except ImportError as exc:
                    raise MTUnavailable(
                        "IndicTrans2 needs IndicTransToolkit: "
                        "pip install -r requirements-mt.txt"
                    ) from exc

            try:
                tokenizer = AutoTokenizer.from_pretrained(
                    self.model_name, trust_remote_code=True
                )
                model = AutoModelForSeq2SeqLM.from_pretrained(
                    self.model_name, trust_remote_code=True
                ).to(self.device)
            except OSError as exc:
                raise MTUnavailable(
                    f"could not load {self.model_name}: {exc}. If the model is gated, "
                    "accept its licence on huggingface.co and run `huggingface-cli login`."
                ) from exc
            model.eval()
            loaded = (tokenizer, model, IndicProcessor(inference=True))
            self._loaded[self.model_name] = loaded
            return loaded

    # -- translation ---------------------------------------------------------

    def _key(self, text: str, target_language: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
        return (
            f"mt:{self.name}:b{NUM_BEAMS}:pv{PROTECTION_VERSION}:"
            f"{self.source_language}>{target_language}:{digest}"
        )

    def _codes(self, target_language: str) -> tuple[str, str]:
        try:
            return FLORES_CODES[self.source_language], FLORES_CODES[target_language]
        except KeyError as exc:
            raise MTUnavailable(f"IndicTrans2 has no code for {exc.args[0]!r}") from None

    def translate_many(
        self,
        texts: list[str],
        target_language: str,
        terms: list[list[str]] | None = None,
    ) -> list[str]:
        """Translate a batch, protecting on-screen terms (terms.py) and serving
        what it can from the cache.

        `terms[i]` are text i's own protected terms; the script glossary is
        added to each. The cache holds the model's output for the PROTECTED
        text, so a glossary change correctly misses."""
        protected = [
            protect(text, self.glossary, terms[index] if terms else [])
            for index, text in enumerate(texts)
        ]

        raw = self._translate_raw([p for p, _ in protected], target_language)
        return [
            fix_punctuation(text, restore(output, originals))
            for text, (_, originals), output in zip(texts, protected, raw)
        ]

    def _translate_raw(self, texts: list[str], target_language: str) -> list[str]:
        results: dict[int, str] = {}
        pending: list[tuple[int, str]] = []
        for index, text in enumerate(texts):
            cached = self.cache.get(self._key(text, target_language))
            if cached is not None:
                results[index] = cached
            else:
                pending.append((index, text))

        if pending:
            src, tgt = self._codes(target_language)
            tokenizer, model, processor = self._load()
            import torch

            # Similar lengths batch together: padding is wasted work, and a short
            # line batched with a paragraph waits for the paragraph.
            pending.sort(key=lambda item: len(item[1]))
            for start in range(0, len(pending), BATCH_SIZE):
                chunk = pending[start : start + BATCH_SIZE]
                batch = processor.preprocess_batch(
                    [text for _, text in chunk], src_lang=src, tgt_lang=tgt
                )
                # Generation is not safe to run concurrently on one model, and
                # on CPU there is nothing to gain from trying.
                with self._lock, torch.inference_mode():
                    inputs = tokenizer(
                        batch,
                        truncation=True,
                        padding="longest",
                        return_tensors="pt",
                        return_attention_mask=True,
                    ).to(self.device)
                    generated = self._generate(model, inputs)
                decoded = tokenizer.batch_decode(
                    generated, skip_special_tokens=True, clean_up_tokenization_spaces=True
                )
                outputs = processor.postprocess_batch(decoded, lang=tgt)
                for (index, text), output in zip(chunk, outputs):
                    output = " ".join(output.split())
                    results[index] = output
                    self.cache.put(self._key(text, target_language), output)

        return [results[i] for i in range(len(texts))]

    _use_cache = True
    """IndicTrans2's model code predates the Cache objects newer transformers
    releases (>= ~4.48) pass during generation, and crashes reading
    `past_key_values[0][0]`. Rather than pin an old transformers, generation
    falls back to no KV cache the first time that happens - slower per batch,
    correct on every version."""

    def _generate(self, model, inputs):
        options = dict(
            min_length=0,
            max_length=MAX_LENGTH,
            num_beams=NUM_BEAMS,
            num_return_sequences=1,
        )
        if IndicTransMT._use_cache:
            try:
                return model.generate(**inputs, use_cache=True, **options)
            except AttributeError as exc:
                if "shape" not in str(exc):
                    raise
                IndicTransMT._use_cache = False
        return model.generate(**inputs, use_cache=False, **options)

    def translate(self, text: str, target_language: str) -> str:
        return self.translate_many([text], target_language)[0]

    # -- the Drafter protocol ------------------------------------------------

    def prepare(self, segments: Iterable[Segment], target_language: str) -> None:
        """Build the script's glossary, then translate the whole track in
        batches before the per-segment loop asks for drafts one at a time -
        batching is several times faster on CPU."""
        segments = list(segments)
        self.glossary = glossary((s.bold_terms for s in segments), (s.text for s in segments))
        self.translate_many(
            [s.text for s in segments], target_language, [s.bold_terms for s in segments]
        )

    def draft(self, segment: Segment, target_language: str) -> str:
        return self.translate_many([segment.text], target_language, [segment.bold_terms])[0]
