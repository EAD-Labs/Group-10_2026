"""Dubbing jobs: one script taken to one language track, in a background thread.

Jobs live in memory, with each job's state also written to its folder so a
restarted server still lists finished work. No database - this is a demo
surface over the library, not the product.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field

from ..config import settings
from ..parsing.parser import parse_script
from ..pipeline.runner import PipelineConfig, build_providers, run_track
from ..schemas import AudioAsset, TranslatedSegment
from ..timeline.qa import summarise
from .library import Library

JOBS_DIR = os.path.abspath(os.path.join(settings().out_dir, "jobs"))
FEED_LENGTH = 8


@dataclass
class Job:
    id: str
    script_name: str
    language: str
    translator: str
    tts: str
    aligner: str
    video_name: str | None = None
    video_path: str | None = None
    title: str | None = None
    voice: str | None = None
    pace: float = 1.0
    status: str = "queued"  # queued | running | done | error
    stage: str | None = None
    progress: dict[str, list[int]] = field(default_factory=dict)
    stubs: list[str] = field(default_factory=list)
    error: str | None = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    feed: list[dict] = field(default_factory=list)
    """The latest lines translated or voiced, newest last - the live view."""
    summary: dict = field(default_factory=dict)

    @property
    def folder(self) -> str:
        return os.path.join(JOBS_DIR, self.id)

    @property
    def track_dir(self) -> str:
        return os.path.join(self.folder, self.language)

    def save(self) -> None:
        os.makedirs(self.folder, exist_ok=True)
        with open(os.path.join(self.folder, "job.json"), "w", encoding="utf-8") as handle:
            json.dump(asdict(self), handle, indent=1)

    def file_url(self, path: str | None) -> str | None:
        """A URL for a file inside this job's folder; None for anything else."""
        if not path:
            return None
        absolute = os.path.abspath(path)
        if not absolute.startswith(self.folder + os.sep) or not os.path.exists(absolute):
            return None
        relative = os.path.relpath(absolute, self.folder).replace(os.sep, "/")
        return f"/api/jobs/{self.id}/files/{relative}?v={int(os.path.getmtime(absolute))}"


JOBS: dict[str, Job] = {}
LOCKS: dict[str, threading.Lock] = {}


def register(job: Job) -> None:
    JOBS[job.id] = job
    LOCKS[job.id] = threading.Lock()


def restore(library: Library) -> None:
    """Reload every job saved under JOBS_DIR; a run cut off by a restart is
    reported as failed rather than left spinning."""
    if not os.path.isdir(JOBS_DIR):
        return
    for name in os.listdir(JOBS_DIR):
        path = os.path.join(JOBS_DIR, name, "job.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                job = Job(**json.load(handle))
        except (OSError, TypeError, ValueError):
            continue
        if job.status in {"queued", "running"}:
            job.status, job.error = "error", "server restarted during the run"
        if not job.title:  # jobs from before titles were recorded
            job.title = library.title_for(job.script_name)
        register(job)


class _Feed:
    """Turns the runner's progress items into the page's live feed."""

    def __init__(self, job: Job) -> None:
        self.job = job
        self.sources: dict[str, str] = {}
        self.texts: dict[str, str] = {}

    def __call__(self, stage: str, done: int, total: int, item=None) -> None:
        job = self.job
        job.stage = stage
        job.progress[stage] = [done, total]
        event = None
        if isinstance(item, TranslatedSegment):
            self.texts[item.segment_id] = item.text
            event = {
                "kind": "translated",
                "id": item.segment_id,
                "source": self.sources.get(item.segment_id, item.source_text),
                "text": item.text,
                "stage": item.stage,
                "fitted": item.fitted,
            }
        elif isinstance(item, AudioAsset):
            event = {
                "kind": "voiced",
                "id": item.segment_id,
                "source": self.sources.get(item.segment_id, ""),
                "text": self.texts.get(item.segment_id, ""),
                "seconds": round(item.duration, 2),
                "audio": job.file_url(item.path),
            }
        if event is not None:
            job.feed = (job.feed + [event])[-FEED_LENGTH:]


def run(job: Job, config: PipelineConfig, script_path: str, duration: float | None) -> None:
    feed = _Feed(job)
    with LOCKS[job.id]:
        job.status = "running"
        job.started = time.time()
        job.save()
        try:
            script = parse_script(script_path, language="en", duration=duration)
            feed.sources.update({s.id: s.text for s in script.segments})
            feed("parse", len(script.segments), len(script.segments))
            providers = build_providers(config, script)
            job.stubs = providers.stubs
            track = run_track(script, config, progress=feed, providers=providers)
            job.summary = summarise(track)
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 - reported to the page, not swallowed
            traceback.print_exc()
            job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
        job.finished = time.time()
        job.save()


def start(job: Job, config: PipelineConfig, script_path: str, duration: float | None) -> None:
    register(job)
    job.save()
    threading.Thread(target=run, args=(job, config, script_path, duration), daemon=True).start()
