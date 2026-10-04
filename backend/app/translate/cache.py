"""On-disk cache for translations.

LLM calls are metered and the client named cost as a constraint (HLD S12.2).
Re-running a track after fixing one segment must not re-pay for the other
ninety-four, and a demo must not cost anything at all the second time.

Keyed on everything that would change the answer - source text, target
language, budget, model, attempt index - so a changed budget correctly misses
rather than returning a translation fitted to the old one.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading


class TranslationCache:
    AUTOSAVE_EVERY = 20
    """Flush this often during a run. A track is ~95 metered calls; losing all
    of them to a crash at segment 90 is the difference between a free re-run
    and paying twice."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self._entries: dict[str, str] = {}
        self._lock = threading.Lock()
        self._unsaved = 0
        self.hits = 0
        self.misses = 0
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    self._entries = json.load(handle)
            except (OSError, json.JSONDecodeError):
                # A corrupt cache is a performance problem, never a correctness
                # one: drop it and re-earn the entries.
                self._entries = {}

    @staticmethod
    def key(source: str, language: str, budget_units: int, model: str, attempt: int) -> str:
        raw = f"{model}\x00{language}\x00{budget_units}\x00{attempt}\x00{source}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def get(self, key: str) -> str | None:
        value = self._entries.get(key)
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
        return value

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._entries[key] = value
            self._unsaved += 1
            due = self.path and self._unsaved >= self.AUTOSAVE_EVERY
        if due:
            self.save()

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with self._lock:
            # Write-then-replace: a crash mid-write must not leave a truncated
            # cache that the next run silently discards as corrupt.
            temporary = f"{self.path}.tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(self._entries, handle, ensure_ascii=False, indent=1)
            os.replace(temporary, self.path)
            self._unsaved = 0

    def __len__(self) -> int:
        return len(self._entries)
