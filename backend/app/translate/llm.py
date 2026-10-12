"""Chat-model providers for the fitting translator.

The translator does not know which model it is talking to. That matters for
two reasons: the loop has to be testable without spending credits or reaching
the network, and the client's provider choice is theirs to change.

Both providers in use speak the OpenAI chat-completions shape, so one client
serves them: `SarvamChat` (sarvam-105b - the default, since the same Sarvam key
already pays for speech) and `GroqChat` (GPT-OSS 120B, kept as an alternative).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..config import find_dotenv, load_dotenv, settings  # noqa: F401 - re-exported
from ..http import ProviderError, RetryWith, post_with_retry

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"

SARVAM_CHAT_ENDPOINT = "https://api.sarvam.ai/v1/chat/completions"
"""v1, not v2: v2 is behind beta access."""

DEFAULT_MAX_TOKENS = 500
"""Cap on the reply, because the provider counts RESERVED tokens against the
rate limit, not used ones. Left unset a request reserved over 3000 against a
free-tier ceiling of 8000 per minute.

Not smaller, though: GPT-OSS is a reasoning model and spends completion tokens
thinking before it answers. At 256 the reasoning consumed the whole budget,
the response came back with finish_reason "length" and an EMPTY content field,
and the loop correctly - but unhelpfully - reported 95 empty translations."""

DEFAULT_REASONING_EFFORT = "low"
"""Translating one sentence under a length budget needs little deliberation,
and reasoning tokens are the main thing standing between us and the rate
limit. Kept configurable because a harder target language may want more."""


class LLMError(ProviderError):
    """The provider could not be reached, or refused the request."""


class TruncatedReply(LLMError):
    """The reply hit max_tokens before producing any content.

    A reasoning model spends completion tokens thinking before it answers, so a
    cap tight enough to protect the rate limit can be consumed entirely by the
    reasoning on a long line. Retried with a larger budget rather than reported
    as an empty translation."""


@runtime_checkable
class ChatModel(Protocol):
    """One turn in, one string out. Deliberately the smallest useful surface."""

    name: str

    def complete(self, system: str, user: str, *, temperature: float = 0.3) -> str: ...


class OpenAICompatibleChat:
    """Any OpenAI-shaped chat-completions endpoint. Subclasses name the
    endpoint, the key and how the key is sent."""

    endpoint: str = ""
    provider: str = ""
    key_variable: str = ""
    default_model: str = ""
    null_disables_reasoning = False
    """Some providers reason by default unless sent an explicit null."""

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 5,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
    ) -> None:
        self.model = model or self.default_model
        self.name = f"{self.provider}:{self.model}"
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self._api_key = api_key if api_key is not None else self._configured_key()

    def _configured_key(self) -> str:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def complete(self, system: str, user: str, *, temperature: float = 0.3) -> str:
        if not self._api_key:
            raise LLMError(
                f"{self.key_variable} is not set. Put it in the environment or in a .env "
                "file at the repository root (see .env.example). Never commit it."
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": self.max_tokens,
        }
        if self.reasoning_effort or self.null_disables_reasoning:
            payload["reasoning_effort"] = self.reasoning_effort

        def parse(response) -> str:
            try:
                return self._extract(response.json())
            except TruncatedReply as exc:
                # The reasoning outgrew the budget. A longer source line needs
                # more room to think; give it more rather than failing a
                # segment that is otherwise fine.
                payload["max_tokens"] = min(payload["max_tokens"] * 2, 2000)
                raise RetryWith(payload, str(exc)) from exc

        return post_with_retry(
            self.endpoint,
            payload,
            headers=self._headers(),
            parse=parse,
            label=self.name,
            timeout=self.timeout,
            max_retries=self.max_retries,
            error=LLMError,
        )

    @staticmethod
    def _extract(body: dict) -> str:
        try:
            choice = body["choices"][0]
            content = (choice["message"].get("content") or "").strip()
        except (KeyError, IndexError, AttributeError) as exc:
            raise LLMError(f"unexpected response shape: {str(body)[:300]}") from exc

        if not content and choice.get("finish_reason") == "length":
            # The model spent its whole completion budget reasoning. Silent
            # truncation would surface downstream as "empty translation",
            # which points at the wrong thing entirely.
            raise TruncatedReply(
                "reply truncated before any content: the reasoning consumed "
                f"max_tokens"
            )
        return content


class GroqChat(OpenAICompatibleChat):
    """GPT-OSS 120B via Groq's OpenAI-compatible endpoint."""

    endpoint = GROQ_ENDPOINT
    provider = "groq"
    key_variable = "GROQ_API_KEY"
    default_model = GROQ_DEFAULT_MODEL

    def _configured_key(self) -> str:
        return settings().groq_api_key


class SarvamChat(OpenAICompatibleChat):
    """Sarvam's sarvam-105b, an Indic-first model, via chat completions v1.

    The docs list both `Authorization: Bearer` and `api-subscription-key` as
    the auth header in different places, so both are sent with the same key.

    Reasoning is switched OFF, with an explicit `"reasoning_effort": null`.
    Sarvam reasons by default (medium), and even "low" is not low: measured on
    a one-line shortening request, "low" spent 799 of 800 tokens reasoning and
    returned nothing (finish_reason "length"); null returned the edit in 11
    tokens and 0.7 s. Omitting the field is not the same as null - omitted
    means the default, which is what failed 10 of 11 shortenings in the first
    full run."""

    endpoint = SARVAM_CHAT_ENDPOINT
    provider = "sarvam"
    key_variable = "SARVAM_API_KEY"

    null_disables_reasoning = True

    def __init__(self, model: str | None = None, **options) -> None:
        options.setdefault("max_tokens", 800)
        options.setdefault("reasoning_effort", None)
        super().__init__(model or settings().sarvam_llm_model, **options)

    def _configured_key(self) -> str:
        return settings().sarvam_api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "api-subscription-key": self._api_key,
        }


class ScriptedChat:
    """A fake model that returns queued replies, for tests and offline runs.

    The fitting loop's logic - budgeting, measuring, retrying, escalating - is
    the part worth testing, and none of it needs a network call. Queue a reply
    per attempt and the loop can be driven through every branch deterministically.
    """

    def __init__(self, replies: list[str] | None = None, name: str = "scripted") -> None:
        self.replies = list(replies or [])
        self.name = name
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, temperature: float = 0.3) -> str:
        self.calls.append((system, user))
        if not self.replies:
            return ""
        return self.replies.pop(0)
