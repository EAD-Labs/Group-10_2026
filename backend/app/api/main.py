"""The HTTP face of the pipeline, and the minimal review UI it serves.

    cd backend
    uvicorn app.api.main:app --reload
    # open http://localhost:8000

A job is one script taken to one language track. It runs in a background
thread; the page polls its progress (HLD S10.2's job-progress endpoint) and a
live feed of the lines as they are translated and voiced, then plays the dub
against the original and shows every segment - English, MT draft, final text,
budget, measured audio - letting a reviewer rewrite one segment and regenerate
only that one (UC-03).

Deliberately small: jobs live in memory, with each job's state also written to
its folder so a restarted server still lists finished work. No database, no
auth - this is a demo surface over the library, not the product.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import settings
from ..duration.calibrate import calibrated_rate
from ..duration.model import voice_key
from ..media.probe import probe
from ..parsing.parser import parse_script
from ..pipeline import store
from ..pipeline.registry import ALIGNERS, TRANSLATORS, TTS_PROVIDERS, is_stub
from ..pipeline.runner import STAGES, PipelineConfig, build_providers, run_segments, run_track
from ..schemas import AudioAsset, TranslatedSegment
from ..translate.indictrans import FLORES_CODES
from ..translate.manual import ManualTranslator
from ..translate.prompts import language_name
from ..tts import sarvam
from .library import Library

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
SAMPLES = os.path.join(os.path.dirname(BACKEND), "samples")
JOBS_DIR = os.path.abspath(os.path.join(settings().out_dir, "jobs"))
LIBRARY = Library(SAMPLES, os.path.join(settings().out_dir, "thumbs"))
FEED_LENGTH = 8

app = FastAPI(title="Spoken Tutorial dubbing")


# -- jobs ----------------------------------------------------------------------


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


JOBS: dict[str, Job] = {}
LOCKS: dict[str, threading.Lock] = {}


def _restore_jobs() -> None:
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
            job.title = next(
                (t.title for t in LIBRARY.tutorials() if os.path.basename(t.script) == job.script_name),
                os.path.splitext(job.script_name)[0],
            )
        JOBS[job.id] = job
        LOCKS[job.id] = threading.Lock()


_restore_jobs()


def _job(job_id: str) -> Job:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"no job {job_id}")
    return job


def _summarise(track) -> dict:
    """The headline numbers the history list and result screen show."""
    translations = track.translations
    qa = track.qa
    return {
        "segments": len(translations),
        "on_time": sum(1 for r in qa.segments if r.within_drift) if qa else None,
        "kept": sum(1 for t in translations if t.stage == "draft"),
        "condensed": sum(1 for t in translations if t.stage == "shortened"),
        "review": sum(1 for t in translations if not t.fitted),
        "max_drift": qa.max_drift if qa else None,
        "median_pause": qa.median_pause if qa else None,
    }


def _run(job: Job, config: PipelineConfig, script_path: str, duration: float | None) -> None:
    sources: dict[str, str] = {}
    texts: dict[str, str] = {}

    def progress(stage: str, done: int, total: int, item=None) -> None:
        job.stage = stage
        job.progress[stage] = [done, total]
        event = None
        if isinstance(item, TranslatedSegment):
            texts[item.segment_id] = item.text
            event = {
                "kind": "translated",
                "id": item.segment_id,
                "source": sources.get(item.segment_id, item.source_text),
                "text": item.text,
                "stage": item.stage,
                "fitted": item.fitted,
            }
        elif isinstance(item, AudioAsset):
            event = {
                "kind": "voiced",
                "id": item.segment_id,
                "source": sources.get(item.segment_id, ""),
                "text": texts.get(item.segment_id, ""),
                "seconds": round(item.duration, 2),
                "audio": _file_url(job, item.path),
            }
        if event is not None:
            job.feed = (job.feed + [event])[-FEED_LENGTH:]

    with LOCKS[job.id]:
        job.status = "running"
        job.started = time.time()
        job.save()
        try:
            script = parse_script(script_path, language="en", duration=duration)
            sources.update({s.id: s.text for s in script.segments})
            progress("parse", len(script.segments), len(script.segments))
            providers = build_providers(config, script)
            # Only the stages that produce the numbers; the manifest exporter is
            # a stand-in for a later project format and changes nothing heard.
            job.stubs = sorted(
                p.name for p in (providers.translator, providers.tts, providers.aligner) if is_stub(p)
            )
            track = run_track(script, config, progress=progress, providers=providers)
            job.summary = _summarise(track)
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 - reported to the page, not swallowed
            traceback.print_exc()
            job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
        job.finished = time.time()
        job.save()


def _save_upload(upload: UploadFile, folder: str) -> str:
    name = os.path.basename(upload.filename or "upload")
    path = os.path.join(folder, name)
    with open(path, "wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return path


def _sample(name: str) -> str:
    """A file inside the samples folder, by its path relative to it."""
    try:
        return LIBRARY.resolve(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# -- endpoints -----------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    """What this machine can actually run, so the page can default sensibly
    and say why a real provider is unavailable rather than failing a job."""
    try:
        import IndicTransToolkit  # noqa: F401
        import torch  # noqa: F401
        import transformers  # noqa: F401

        mt = True
    except ImportError:
        mt = False
    config = settings()
    return {
        "groq_key": bool(config.groq_api_key),
        "sarvam_key": bool(config.sarvam_api_key),
        "indictrans_installed": mt,
        "indictrans_model": config.indictrans_model,
        "translators": sorted(TRANSLATORS),
        "tts": sorted(TTS_PROVIDERS),
        "aligners": sorted(ALIGNERS),
        "stages": list(STAGES),
    }


@app.get("/api/samples")
def samples() -> dict:
    """Every English script and video under samples/, by relative path."""
    return {
        "scripts": [t.script for t in LIBRARY.tutorials()],
        "videos": [v.replace(os.sep, "/") for v in LIBRARY.english_videos()],
    }


@app.get("/api/library")
def library() -> dict:
    """The tutorials ready to dub: each English script paired with its video."""
    return {"tutorials": LIBRARY.as_dicts()}


@app.get("/api/library/poster")
def poster(video: str) -> FileResponse:
    try:
        path = LIBRARY.poster(video)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not path:
        raise HTTPException(404, "no poster")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/library/video")
def library_video(video: str) -> FileResponse:
    try:
        return FileResponse(LIBRARY.resolve(video))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


def _language_codes() -> list[str]:
    """Languages both the translator and the voice cover."""
    return [c for c in FLORES_CODES if c != "en" and c in sarvam.LANGUAGE_CODES]


@app.get("/api/voices")
def voices() -> dict:
    return {"default": settings().sarvam_speaker, "voices": sarvam.voices()}


@app.get("/api/languages")
def languages(voice: str | None = None, pace: float = 1.0) -> dict:
    """Each target language, and whether this voice at this pace has been
    measured in it - a job that has not runs the calibrate stage first."""
    provider = f"sarvam:{settings().sarvam_tts_model}"
    key = voice_key(provider, voice or settings().sarvam_speaker, pace)
    return {
        "languages": [
            {"code": c, "name": language_name(c), "rate": calibrated_rate(key, c)}
            for c in _language_codes()
        ]
    }


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return [asdict(j) for j in sorted(JOBS.values(), key=lambda j: -j.created)]


@app.post("/api/jobs")
def create_job(
    script: UploadFile | None = File(None),
    video: UploadFile | None = File(None),
    sample_script: str | None = Form(None),
    sample_video: str | None = Form(None),
    language: str = Form("ta"),
    translator: str = Form("indictrans+sarvam"),
    tts: str = Form("sarvam"),
    aligner: str | None = Form(None),
    duration: float | None = Form(None),
    workers: int = Form(4),
    voice: str | None = Form(None),
    pace: float = Form(1.0),
) -> dict:
    if not 0.5 <= pace <= 2.0:
        raise HTTPException(400, "pace must be between 0.5 and 2.0")
    if language not in _language_codes():
        raise HTTPException(400, f"unsupported language {language!r}")
    if voice and tts == "sarvam" and voice not in {v["id"] for v in sarvam.voices()}:
        raise HTTPException(400, f"unknown voice {voice!r}")
    for value, table, kind in (
        (translator, TRANSLATORS, "translator"),
        (tts, TTS_PROVIDERS, "tts"),
        (aligner or "vad", ALIGNERS, "aligner"),
    ):
        if value not in table:
            raise HTTPException(400, f"unknown {kind} {value!r}")

    job_id = uuid.uuid4().hex[:10]
    inputs = os.path.join(JOBS_DIR, job_id, "inputs")
    os.makedirs(inputs, exist_ok=True)

    if script is not None and script.filename:
        script_path = _save_upload(script, inputs)
    elif sample_script:
        script_path = _sample(sample_script)
    else:
        raise HTTPException(400, "upload a script or choose a sample")

    video_path = None
    if video is not None and video.filename:
        video_path = _save_upload(video, inputs)
    elif sample_video:
        video_path = _sample(sample_video)
    if video_path:
        try:
            duration = probe(video_path).duration
        except ValueError as exc:
            raise HTTPException(400, f"cannot read the video: {exc}") from exc

    # Real audio needs the real aligner; the stub only makes sense for silence.
    aligner = aligner or ("clip-bounds" if tts == "silent" else "vad")
    title = next(
        (t.title for t in LIBRARY.tutorials() if sample_script and t.script == sample_script),
        os.path.splitext(os.path.basename(script_path))[0],
    )
    job = Job(
        id=job_id,
        script_name=os.path.basename(script_path),
        video_name=os.path.basename(video_path) if video_path else None,
        video_path=video_path,
        title=title,
        voice=(voice or settings().sarvam_speaker) if tts == "sarvam" else None,
        language=language,
        translator=translator,
        tts=tts,
        aligner=aligner,
        pace=pace,
    )
    config = PipelineConfig(
        language=language,
        out_dir=job.folder,
        translator=translator,
        tts=tts,
        aligner=aligner,
        exporters=["srt", "manifest", "mixdown"],
        voice=voice or None,
        max_workers=max(1, min(workers, 8)),
        video_path=video_path,
        voice_pace=pace,
    )
    JOBS[job_id] = job
    LOCKS[job_id] = threading.Lock()
    job.save()
    threading.Thread(target=_run, args=(job, config, script_path, duration), daemon=True).start()
    return asdict(job)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return asdict(_job(job_id))


def _file_url(job: Job, path: str | None) -> str | None:
    if not path:
        return None
    absolute = os.path.abspath(path)
    if not absolute.startswith(job.folder + os.sep) or not os.path.exists(absolute):
        return None
    relative = os.path.relpath(absolute, job.folder).replace(os.sep, "/")
    return f"/api/jobs/{job.id}/files/{relative}?v={int(os.path.getmtime(absolute))}"


@app.get("/api/jobs/{job_id}/track")
def get_track(job_id: str) -> dict:
    job = _job(job_id)
    if not os.path.exists(store.path_for(job.track_dir)):
        raise HTTPException(409, "the track is not ready yet")
    script, track, config = store.load(job.track_dir)

    translations = {t.segment_id: t for t in track.translations}
    audio = {a.segment_id: a for a in track.audio}
    qa = {row.segment_id: row for row in (track.qa.segments if track.qa else [])}
    rows = []
    for segment in script.segments:
        t = translations.get(segment.id)
        if t is None:
            continue
        row = qa.get(segment.id)
        rows.append(
            {
                "id": segment.id,
                "start": segment.start,
                "end": segment.end,
                "cue": bool(segment.cue_ids),
                "source": segment.text,
                "draft": t.draft_text,
                "text": t.text,
                "units": t.syllables,
                "budget": t.budget,
                "predicted": t.predicted_duration,
                "actual": row.actual if row else None,
                "drift": row.drift if row else None,
                "pause": row.pause_after if row else None,
                "rate": row.rate_ratio if row else None,
                "fitted": t.fitted,
                "within_drift": row.within_drift if row else None,
                "stage": t.stage,
                "translator": t.translator,
                "attempts": t.attempts,
                "note": t.note,
                "audio": _file_url(job, audio[segment.id].path) if segment.id in audio else None,
            }
        )

    exports = {os.path.basename(p): _file_url(job, p) for p in track.exports}
    summary = {}
    if track.qa:
        summary = {
            "segments": len(rows),
            "fitted": sum(1 for r in rows if r["fitted"]),
            "escalated": sum(1 for r in rows if not r["fitted"]),
            "drafts_kept": sum(1 for r in rows if r["stage"] == "draft"),
            "shortened": sum(1 for r in rows if r["stage"] == "shortened"),
            "within_drift": sum(1 for r in rows if r["within_drift"]),
            "max_drift": track.qa.max_drift,
            "median_pause": track.qa.median_pause,
            "mean_rate_ratio": track.qa.mean_rate_ratio,
            "audio_seconds": sum(a.duration for a in track.audio),
        }
    original = f"/api/jobs/{job.id}/original" if _original_path(job) else None
    return {
        "job": asdict(job),
        "original": original,
        "settings": {
            "language": language_name(job.language),
            "translator": job.translator,
            "tts": job.tts,
            "model": settings().sarvam_tts_model if job.tts == "sarvam" else None,
            "voice": job.voice,
            "pace": job.pace,
            "aligner": job.aligner,
            "rate": round(config.rate_model.rate(job.language), 3),
            "pause_reserve": config.rate_model.pause_reserve,
            "llm": settings().sarvam_llm_model if "sarvam" in job.translator else None,
            "mt": settings().indictrans_model if "indictrans" in job.translator else None,
        },
        "duration": track.duration,
        "summary": summary,
        "exports": exports,
        "rows": rows,
    }


class SegmentEdit(BaseModel):
    text: str | None = None


@app.post("/api/jobs/{job_id}/segments/{segment_id}")
def regenerate_segment(job_id: str, segment_id: str, edit: SegmentEdit) -> dict:
    """UC-03: redo one segment - with the reviewer's text if given, otherwise
    through the configured translator - and rebuild timeline, QA and exports."""
    job = _job(job_id)
    if job.status == "running":
        raise HTTPException(409, "the job is still running")
    with LOCKS[job.id]:
        script, track, config = store.load(job.track_dir)
        if segment_id not in {s.id for s in script.segments}:
            raise HTTPException(404, f"no segment {segment_id}")
        providers = build_providers(config, script)
        if edit.text is not None and edit.text.strip():
            previous = {t.segment_id: t for t in track.translations}
            providers.translator = ManualTranslator({segment_id: edit.text}, previous)
        run_segments(script, track, [segment_id], config, providers=providers)
    return get_track(job_id)


@app.get("/api/jobs/{job_id}/original")
def get_original(job_id: str) -> FileResponse:
    """The English video the job was dubbed from, for side-by-side viewing.

    Only the path recorded at job creation is served, and only if it lies in
    the job's own folder (an upload) or in samples/."""
    path = _original_path(_job(job_id))
    if path is None:
        raise HTTPException(404, "no original video for this job")
    return FileResponse(path)


def _original_path(job: Job) -> str | None:
    allowed = (job.folder + os.sep, os.path.abspath(SAMPLES) + os.sep)
    if job.video_path:
        path = os.path.abspath(job.video_path)
        return path if path.startswith(allowed) and os.path.isfile(path) else None
    # Jobs from before the path was recorded: find the sample by its name.
    if job.video_name:
        for video in LIBRARY.english_videos():
            if os.path.basename(video) == job.video_name:
                return LIBRARY.resolve(video)
    return None


@app.get("/api/jobs/{job_id}/files/{path:path}")
def get_file(job_id: str, path: str) -> FileResponse:
    job = _job(job_id)
    absolute = os.path.abspath(os.path.join(job.folder, path))
    if not absolute.startswith(job.folder + os.sep) or not os.path.isfile(absolute):
        raise HTTPException(404, "no such file")
    return FileResponse(absolute)


app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True), name="ui")
