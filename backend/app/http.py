"""POST with retries, shared by every metered provider.

Groq (shortening) and Sarvam (speech) fail the same ways - rate limits, 5xx,
dropped connections - and both say how long to wait. Each used to carry its own
copy of the loop; this is that loop once.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}
MAX_WAIT = 30.0
RETRY_AFTER_HINT = re.compile(r"try again in ([0-9.]+)s", re.IGNORECASE)


class ProviderError(RuntimeError):
    """The provider could not be reached, or refused the request."""


class RetryWith(Exception):
    """Raised by a `parse` callback to retry at once with a changed payload.

    For failures the provider reports as success - a reasoning model whose
    reply was truncated before any content, say - where waiting would not
    help but asking differently would."""

    def __init__(self, payload: dict, reason: str) -> None:
        super().__init__(reason)
        self.payload = payload


def retry_after(response: Any, fallback: float) -> float:
    """How long the provider asked us to wait; guessing shorter just burns an
    attempt and arrives to the same refusal."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return min(float(header) + 0.5, MAX_WAIT)
        except ValueError:
            pass
    hint = RETRY_AFTER_HINT.search(response.text or "")
    if hint:
        return min(float(hint.group(1)) + 0.5, MAX_WAIT)
    return fallback


def post_with_retry(
    url: str,
    payload: dict,
    *,
    headers: dict[str, str],
    parse: Callable[[Any], T],
    label: str,
    timeout: float = 60.0,
    max_retries: int = 5,
    error: type[ProviderError] = ProviderError,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    import httpx

    last_error = ""
    for attempt in range(max_retries):
        wait = 2.0 * (attempt + 1)
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.HTTPError as exc:
            last_error = str(exc)
        else:
            if response.status_code == 200:
                try:
                    return parse(response)
                except RetryWith as retry:
                    last_error = str(retry)
                    payload = retry.payload
                    if attempt < max_retries - 1:
                        continue
                    raise error(last_error) from retry
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
            if response.status_code not in RETRY_STATUS:
                break
            wait = retry_after(response, wait)

        if attempt < max_retries - 1:
            sleep(wait)

    raise error(f"{label} failed after {max_retries} attempts: {last_error}")
