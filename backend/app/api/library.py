"""The tutorials the demo can dub: English scripts paired with English videos.

Everything under `samples/` is scanned, subfolders included. A script and its
video rarely share a file name ("Table and table properties.docx" vs
"Tables-and-table-properties-in-Writer-English.webm"), so they are paired by
the words of the tutorial's title - taken from the script's opening line
("Welcome to the spoken tutorial on <title>") and its file name - against the
words of the video's file name.

Only English inputs are offered. A script whose narration is not in Latin
script (the client's Tamil script) and a video named for another language (the
client's Tamil dub) are evaluation material, never pipeline inputs.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import asdict, dataclass

from ..media.audio import ffmpeg_binary
from ..media.probe import probe
from ..parsing.docx_reader import SCRIPT_EXTENSIONS
from ..parsing.parser import parse_script

VIDEO_EXTENSIONS = (".webm", ".mkv", ".mp4")

OTHER_LANGUAGES = {
    "tamil", "hindi", "marathi", "telugu", "kannada", "malayalam", "bengali",
    "gujarati", "punjabi", "odia", "oriya", "assamese", "urdu",
}
STOPWORDS = {
    "a", "an", "and", "the", "of", "on", "in", "to", "for", "with", "how",
    "english", "script", "sample", "timed", "spoken", "tutorial", "video",
}
TITLE = re.compile(r"tutorial\s+on\s+(.+?)\s*\.?\s*$", re.IGNORECASE)


@dataclass
class Tutorial:
    id: str
    title: str
    script: str
    """Path relative to the samples folder."""
    video: str | None
    duration: float | None
    lines: int


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def _same_word(a: str, b: str) -> bool:
    """'write' ~ 'writer', 'table' ~ 'tables', 'documents' ~ 'document'."""
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    return len(short) >= 4 and long.startswith(short)


def match_score(title_words: list[str], video_words: list[str]) -> float:
    if not title_words or not video_words:
        return 0.0
    hits = sum(1 for w in set(title_words) if any(_same_word(w, v) for v in video_words))
    return hits / min(len(set(title_words)), len(set(video_words)))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "tutorial"


def _is_english(script) -> bool:
    text = " ".join(s.text for s in script.segments[:10])
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isascii() for c in letters) / len(letters) > 0.8


def _title(script, filename: str) -> str:
    if script.segments:
        found = TITLE.search(script.segments[0].text)
        if found:
            return found.group(1).strip()
    return os.path.splitext(filename)[0].replace("-", " ").replace("_", " ").strip()


class Library:
    def __init__(self, root: str, thumbs_dir: str) -> None:
        self.root = os.path.abspath(root)
        self.thumbs_dir = thumbs_dir
        self._cache: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def resolve(self, relative: str) -> str:
        """An absolute path inside the samples folder, or ValueError."""
        path = os.path.abspath(os.path.join(self.root, relative))
        if not path.startswith(self.root + os.sep) or not os.path.isfile(path):
            raise ValueError(f"no sample {relative!r}")
        return path

    def _files(self) -> tuple[list[str], list[str]]:
        scripts, videos = [], []
        if not os.path.isdir(self.root):
            return scripts, videos
        for folder, _, names in os.walk(self.root):
            for name in names:
                relative = os.path.relpath(os.path.join(folder, name), self.root)
                lower = name.lower()
                if lower.endswith(SCRIPT_EXTENSIONS) and not name.startswith("~$"):
                    scripts.append(relative)
                elif lower.endswith(VIDEO_EXTENSIONS):
                    videos.append(relative)
        return sorted(scripts), sorted(videos)

    def _cached(self, relative: str, build):
        path = os.path.join(self.root, relative)
        mtime = os.path.getmtime(path)
        with self._lock:
            hit = self._cache.get(relative)
            if hit and hit[0] == mtime:
                return hit[1]
        value = build(path)
        with self._lock:
            self._cache[relative] = (mtime, value)
        return value

    def _script(self, relative: str):
        def build(path):
            try:
                return parse_script(path, language="en")
            except Exception:  # noqa: BLE001 - an unreadable file is just not offered
                return None

        return self._cached(relative, build)

    def _duration(self, relative: str) -> float | None:
        def build(path):
            try:
                return probe(path).duration
            except Exception:  # noqa: BLE001
                return None

        return self._cached(relative, build)

    def english_videos(self) -> list[str]:
        _, videos = self._files()
        return [v for v in videos if not set(_words(os.path.basename(v))) & OTHER_LANGUAGES]

    def tutorials(self) -> list[Tutorial]:
        scripts, _ = self._files()
        videos = self.english_videos()
        candidates = []
        for relative in scripts:
            script = self._script(relative)
            if script is None or not script.segments or not _is_english(script):
                continue
            name = os.path.basename(relative)
            title = _title(script, name)
            words = _words(title) + _words(os.path.splitext(name)[0])
            candidates.append((relative, script, title, words))

        # Greedy best-first: each video goes to the script it matches best.
        scored = sorted(
            (
                (match_score(words, _words(os.path.splitext(os.path.basename(v))[0])), relative, v)
                for relative, _, _, words in candidates
                for v in videos
            ),
            reverse=True,
        )
        paired: dict[str, str] = {}
        taken: set[str] = set()
        for score, relative, video in scored:
            if score < 0.5 or relative in paired or video in taken:
                continue
            paired[relative] = video
            taken.add(video)

        out = []
        for relative, script, title, _ in candidates:
            video = paired.get(relative)
            out.append(
                Tutorial(
                    id=_slug(title),
                    title=title,
                    script=relative.replace(os.sep, "/"),
                    video=video.replace(os.sep, "/") if video else None,
                    duration=self._duration(video) if video else None,
                    lines=len(script.segments),
                )
            )
        return sorted(out, key=lambda t: t.title.lower())

    def as_dicts(self) -> list[dict]:
        return [asdict(t) for t in self.tutorials()]

    def title_for(self, script_name: str) -> str:
        """The tutorial's title for a script, by file name or relative path;
        the bare file name for a script that is not in the library."""
        name = os.path.basename(script_name)
        return next(
            (t.title for t in self.tutorials() if t.script == script_name or os.path.basename(t.script) == name),
            os.path.splitext(name)[0],
        )

    def video_named(self, name: str) -> str | None:
        """The absolute path of an English video in the library, by file name."""
        for video in self.english_videos():
            if os.path.basename(video) == name:
                return self.resolve(video)
        return None

    def poster(self, relative_video: str) -> str | None:
        """A JPEG frame from early in the video, made once and cached."""
        video = self.resolve(relative_video)
        os.makedirs(self.thumbs_dir, exist_ok=True)
        target = os.path.join(self.thumbs_dir, _slug(relative_video) + ".jpg")
        if os.path.exists(target) and os.path.getmtime(target) >= os.path.getmtime(video):
            return target
        duration = self._duration(os.path.relpath(video, self.root)) or 0
        at = min(12.0, duration / 3) if duration else 5.0
        try:
            subprocess.run(
                [ffmpeg_binary(), "-y", "-loglevel", "error", "-ss", f"{at:.1f}", "-i", video,
                 "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", target],
                check=True, timeout=60, capture_output=True,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        return target if os.path.exists(target) else None
