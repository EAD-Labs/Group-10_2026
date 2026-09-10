
"""A thin HTTP wrapper around the pipeline library, for the frontend.

No new pipeline logic lives here - every endpoint is a direct call into
parsing.parser, media.probe or pipeline.runner, and every response body is one
of the Pydantic models in schemas.py, unchanged. State is two in-memory dicts
keyed by a generated id: fine for a single-user demo, not a substitute for the
HLD's PostgreSQL-backed project store.

    uvicorn app.api:app --reload
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .duration.model import RateModel
from .media.probe import probe
from .parsing.parser import parse_script
from .pipeline.registry import ALIGNERS, EXPORTERS, TRANSLATORS, TTS_PROVIDERS
from .pipeline.runner import PipelineConfig, run_segments, run_track
from .schemas import LanguageTrack, ParsedScript

# Mirrors app/run.py's STUBBED set - the frontend renders the same warning a
# CLI demo prints, so nobody mistakes a stub's arithmetic for real audio.
STUBBED_STAGES = {"echo", "silent", "clip-bounds", "manifest"}

app = FastAPI(title="Spoken Tutorial Generator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "stg-uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Generated audio clips and exports (SRT/manifest) live under UPLOAD_DIR - serve
# them directly rather than adding download endpoints per file type. Media, not
# an API response: the frontend's <audio> tags and export "Download" buttons
# point straight at these URLs.
app.mount("/media", StaticFiles(directory=UPLOAD_DIR), name="media")

_scripts: dict[str, ParsedScript] = {}
_script_paths: dict[str, str] = {}
_tracks: dict[tuple[str, str], LanguageTrack] = {}


def _media_url(path: str) -> str:
    """Turn an absolute filesystem path under UPLOAD_DIR into a /media URL."""
    rel = os.path.relpath(path, UPLOAD_DIR).replace(os.sep, "/")
    return f"/media/{rel}"


class ScriptResponse(BaseModel):
    id: str
    script: ParsedScript


class ScriptSummary(BaseModel):
    id: str
    source: str
    language: str
    duration: float
    segment_count: int
    languages_run: list[str]


class RunRequest(BaseModel):
    language: str
    source_language: str = "en"
    translator: str = "echo"
    tts: str = "silent"
    aligner: str = "clip-bounds"
    exporters: list[str] = ["srt", "manifest"]
    voice: Optional[str] = None


class RunSegmentsRequest(BaseModel):
    language: str
    segment_ids: list[str]


class TrackResponse(BaseModel):
    track: LanguageTrack
    stubbed_stages: list[str]
    audio_urls: dict[str, str]
    """segment_id -> playable /media URL for that segment's synthesised clip."""
    export_urls: list[str]
    """/media URLs parallel to track.exports, for direct download links."""


def _track_response(track: LanguageTrack, stubbed_stages: list[str]) -> TrackResponse:
    return TrackResponse(
        track=track,
        stubbed_stages=stubbed_stages,
        audio_urls={a.segment_id: _media_url(a.path) for a in track.audio},
        export_urls=[_media_url(p) for p in track.exports],
    )


def _stubbed(config: RunRequest) -> list[str]:
    active = {config.translator, config.tts, config.aligner, *config.exporters}
    return sorted(active & STUBBED_STAGES)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/scripts", response_model=ScriptResponse)
async def upload_script(
    script: UploadFile = File(...),
    language: str = Form("en"),
    duration: Optional[float] = Form(None),
    video: Optional[UploadFile] = File(None),
) -> ScriptResponse:
    script_id = uuid.uuid4().hex
    script_path = os.path.join(UPLOAD_DIR, f"{script_id}-{script.filename}")
    with open(script_path, "wb") as handle:
        shutil.copyfileobj(script.file, handle)

    resolved_duration = duration
    if video is not None:
        video_path = os.path.join(UPLOAD_DIR, f"{script_id}-{video.filename}")
        with open(video_path, "wb") as handle:
            shutil.copyfileobj(video.file, handle)
        resolved_duration = probe(video_path).duration

    try:
        parsed = parse_script(script_path, language=language, duration=resolved_duration)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    _scripts[script_id] = parsed
    _script_paths[script_id] = script_path
    return ScriptResponse(id=script_id, script=parsed)


@app.get("/api/scripts/{script_id}", response_model=ScriptResponse)
def get_script(script_id: str) -> ScriptResponse:
    parsed = _scripts.get(script_id)
    if parsed is None:
        raise HTTPException(status_code=404, detail="unknown script id")
    return ScriptResponse(id=script_id, script=parsed)


@app.post("/api/scripts/{script_id}/run", response_model=TrackResponse)
def run(script_id: str, body: RunRequest) -> TrackResponse:
    parsed = _scripts.get(script_id)
    if parsed is None:
        raise HTTPException(status_code=404, detail="unknown script id")

    for name, table in (
        (body.translator, TRANSLATORS),
        (body.tts, TTS_PROVIDERS),
        (body.aligner, ALIGNERS),
    ):
        if name not in table:
            raise HTTPException(status_code=422, detail=f"unknown provider {name!r}")
    for name in body.exporters:
        if name not in EXPORTERS:
            raise HTTPException(status_code=422, detail=f"unknown exporter {name!r}")

    out_dir = os.path.join(UPLOAD_DIR, script_id, "out")
    config = PipelineConfig(
        language=body.language,
        out_dir=out_dir,
        translator=body.translator,
        tts=body.tts,
        aligner=body.aligner,
        exporters=list(body.exporters),
        voice=body.voice,
        rate_model=RateModel(),
    )
    track = run_track(parsed, config)
    _tracks[(script_id, body.language)] = track
    return _track_response(track, _stubbed(body))


@app.post("/api/scripts/{script_id}/run-segments", response_model=TrackResponse)
def rerun_segments(script_id: str, body: RunSegmentsRequest) -> TrackResponse:
    parsed = _scripts.get(script_id)
    if parsed is None:
        raise HTTPException(status_code=404, detail="unknown script id")
    track = _tracks.get((script_id, body.language))
    if track is None:
        raise HTTPException(
            status_code=404, detail="no track for this language yet - call /run first"
        )

    out_dir = os.path.join(UPLOAD_DIR, script_id, "out")
    config = PipelineConfig(language=body.language, out_dir=out_dir, rate_model=RateModel())
    updated = run_segments(parsed, track, body.segment_ids, config)
    _tracks[(script_id, body.language)] = updated
    run_request = RunRequest(language=body.language)
    return _track_response(updated, _stubbed(run_request))


@app.get("/api/scripts", response_model=list[ScriptSummary])
def list_scripts() -> list[ScriptSummary]:
    """Every script uploaded this session - real session state, not a
    database-backed project store (there isn't one yet)."""
    return [
        ScriptSummary(
            id=script_id,
            source=script.source,
            language=script.language,
            duration=script.duration,
            segment_count=len(script.segments),
            languages_run=sorted(lang for (sid, lang) in _tracks if sid == script_id),
        )
        for script_id, script in _scripts.items()
    ]
