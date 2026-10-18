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

Jobs themselves - state, background runs, the live feed - are in jobs.py.
"""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import asdict

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import settings
from ..duration.calibrate import calibrated_rate
from ..duration.model import voice_key
from ..media.probe import probe
from ..pipeline import store
from ..pipeline.registry import ALIGNERS, TRANSLATORS, TTS_PROVIDERS
from ..pipeline.runner import STAGES, PipelineConfig, build_providers, run_segments
from ..timeline.qa import needs_review, summarise
from ..translate.indictrans import FLORES_CODES
from ..translate.manual import ManualTranslator
from ..translate.prompts import language_name
from ..tts import sarvam
from . import jobs
from .jobs import Job
from .library import Library

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(BACKEND)
SAMPLES = os.path.join(ROOT, "samples")
FRONTEND = os.path.join(ROOT, "frontend")
LIBRARY = Library(SAMPLES, os.path.join(settings().out_dir, "thumbs"))

app = FastAPI(title="Spoken Tutorial dubbing")
jobs.restore(LIBRARY)


def _job(job_id: str) -> Job:
    job = jobs.JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"no job {job_id}")
    return job


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
    return [asdict(j) for j in sorted(jobs.JOBS.values(), key=lambda j: -j.created)]


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
    inputs = os.path.join(jobs.JOBS_DIR, job_id, "inputs")
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
    job = Job(
        id=job_id,
        script_name=os.path.basename(script_path),
        video_name=os.path.basename(video_path) if video_path else None,
        video_path=video_path,
        title=LIBRARY.title_for(sample_script or script_path),
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
        exporters=["script", "srt", "mixdown", "manifest"],
        voice=voice or None,
        max_workers=max(1, min(workers, 8)),
        video_path=video_path,
        voice_pace=pace,
    )
    jobs.start(job, config, script_path, duration)
    return asdict(job)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return asdict(_job(job_id))


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
                "review": needs_review(t, row),
                "stage": t.stage,
                "translator": t.translator,
                "attempts": t.attempts,
                "note": t.note,
                "audio": job.file_url(audio[segment.id].path) if segment.id in audio else None,
            }
        )

    exports = {os.path.basename(p): job.file_url(p) for p in track.exports}
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
        "summary": summarise(track) if track.qa else {},
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
    with jobs.LOCKS[job.id]:
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
    return LIBRARY.video_named(job.video_name) if job.video_name else None


@app.get("/api/jobs/{job_id}/files/{path:path}")
def get_file(job_id: str, path: str) -> FileResponse:
    job = _job(job_id)
    absolute = os.path.abspath(os.path.join(job.folder, path))
    if not absolute.startswith(job.folder + os.sep) or not os.path.isfile(absolute):
        raise HTTPException(404, "no such file")
    return FileResponse(absolute)


# The page (frontend/) is static files, served from the same origin as the API.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="ui")
