"""Persist a finished track so a later process can pick it up.

`run_segments` (HLD UC-03) only earns its keep if the reviewer's correction
can arrive in a different request from the run that made the track - which is
the API's whole shape. The manifest exporter is a deliverable and drops what
regeneration needs (alignments, the parsed script, the run's settings), so the
working state is saved separately, in full.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import TYPE_CHECKING

from ..duration.model import RateModel
from ..schemas import LanguageTrack, ParsedScript

if TYPE_CHECKING:  # pragma: no cover
    from .runner import PipelineConfig

FILENAME = "track.json"


def path_for(track_dir: str) -> str:
    return os.path.join(track_dir, FILENAME)


def _config_dict(config: "PipelineConfig") -> dict:
    data = asdict(config)
    # Provider options may hold live objects (the mixdown's script); only the
    # JSON-safe part is a setting worth persisting.
    data["provider_options"] = json.loads(
        json.dumps(config.provider_options, default=lambda _: None)
    )
    return data


def save(
    track_dir: str, script: ParsedScript, track: LanguageTrack, config: "PipelineConfig"
) -> str:
    os.makedirs(track_dir, exist_ok=True)
    path = path_for(track_dir)
    payload = {
        "config": _config_dict(config),
        "script": script.model_dump(),
        "track": track.model_dump(),
    }
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    os.replace(temporary, path)
    return path


def load(track_dir: str) -> tuple[ParsedScript, LanguageTrack, "PipelineConfig"]:
    from .runner import PipelineConfig

    with open(path_for(track_dir), encoding="utf-8") as handle:
        payload = json.load(handle)
    settings = dict(payload["config"])
    settings["rate_model"] = RateModel(**settings.get("rate_model", {}))
    return (
        ParsedScript.model_validate(payload["script"]),
        LanguageTrack.model_validate(payload["track"]),
        PipelineConfig(**settings),
    )
