"""Where the test materials live, and how a test says "not on this machine".

Sample scripts are committed under samples/. The client's videos are not
(large, and not ours to redistribute), so tests that need them skip - under
pytest as a real skip, and under the plain-script runners as `Skip`.
"""

from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLES = os.path.join(ROOT, "samples")

ENGLISH_SCRIPT = os.path.join(SAMPLES, "Timed-script-sample-english.docx")
TAMIL_SCRIPT = os.path.join(SAMPLES, "Tamil-script-sample.docx")


def media(name: str) -> str:
    """A client video: looked for in samples/ first, then the repository root."""
    for folder in (SAMPLES, ROOT):
        candidate = os.path.join(folder, name)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(SAMPLES, name)


ENGLISH_VIDEO = media("Overview-of-Synfig-English.webm")
TAMIL_VIDEO = media("Overview-of-Synfig-Tamil.webm")

try:
    import pytest

    Skip = pytest.skip.Exception
except ImportError:  # pragma: no cover - the script runners work without pytest

    class Skip(Exception):  # type: ignore[no-redef]
        """Raised when the client media is not available on this machine."""
