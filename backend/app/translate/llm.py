"""Chat-model providers for the fitting translator.

The translator does not know which model it is talking to. That matters for
two reasons: the loop has to be testable without spending credits or reaching
the network, and the client's provider choice is theirs to change.

Groq serves the open-weights GPT-OSS 120B model over an OpenAI-compatible
endpoint, which is what `GroqChat` speaks.
"""

from __future__ import annotations

import os
import re
import time
from typing import Protocol, runtime_checkable

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}

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

RETRY_AFTER_HINT = re.compile(r"try again in ([0-9.]+)s", re.IGNORECASE)


class LLMError(RuntimeError):
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

    Secrets stay out of source control (HLD S10.5) but still need to reach a
    developer's shell; this is the least ceremonious way to do that. Existing
    environment variables win, so a real deployment's injected secrets are
    never overwritten by a stray file.
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


class GroqChat:
    """GPT-OSS 120B via Groq's OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        model: str = GROQ_DEFAULT_MODEL,
        *,
        api_key: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 5,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
    ) -> None:
        load_dotenv()
        self.model = model
        self.name = f"groq:{model}"
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self._api_key = api_key or os.environ.get("GROQ_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def complete(self, system: str, user: str, *, temperature: float = 0.3) -> str:
        if not self._api_key:
            raise LLMError(
                "GROQ_API_KEY is not set. Put it in the environment or in a .env "
                "file at the repository root (see .env.example). Never commit it."
            )

        import httpx

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": self.max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        headers = {"Authorization": f"Bearer {self._api_key}"}

        last_error = ""
        budget = self.max_tokens
        for attempt in range(self.max_retries):
            wait = 2.0 * (attempt + 1)
            payload["max_tokens"] = budget
            try:
                response = httpx.post(
                    GROQ_ENDPOINT, json=payload, headers=headers, timeout=self.timeout
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
            else:
                if response.status_code == 200:
                    try:
                        return self._extract(response.json())
                    except TruncatedReply as exc:
                        # The reasoning outgrew the budget. A longer source
                        # line needs more room to think; give it more rather
                        # than failing a segment that is otherwise fine.
                        last_error = str(exc)
                        budget = min(budget * 2, 2000)
                        wait = 0.0
                        if attempt < self.max_retries - 1:
                            continue
                        raise LLMError(last_error) from exc
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                if response.status_code not in RETRY_STATUS:
                    break
                # The provider says exactly how long to wait; guessing shorter
                # just burns an attempt and arrives to the same refusal.
                wait = self._retry_after(response, wait)

            if attempt < self.max_retries - 1:
                time.sleep(wait)

        raise LLMError(f"{self.name} failed after {self.max_retries} attempts: {last_error}")

    @staticmethod
    def _retry_after(response, fallback: float) -> float:
        header = response.headers.get("retry-after")
        if header:
            try:
                return min(float(header) + 0.5, 30.0)
            except ValueError:
                pass
        hint = RETRY_AFTER_HINT.search(response.text or "")
        if hint:
            return min(float(hint.group(1)) + 0.5, 30.0)
        return fallback

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
