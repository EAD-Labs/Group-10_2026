"""Project manifest export - the stand-in for OpenTimelineIO / Kdenlive XML.

The real editable-project export (HLD S13.1) is a later step. This writes the
same information as JSON so the pipeline has a terminal stage that genuinely
completes, and so the OTIO writer that replaces it has a fixture to be checked
against rather than being written blind.
"""

from __future__ import annotations

import json
import os

from ..schemas import LanguageTrack


class ManifestExporter:
    name = "manifest"

    def export(self, track: LanguageTrack, out_dir: str) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{track.language}-project.json")
        payload = {
            "source": track.source,
            "language": track.language,
            "duration": track.duration,
            "timeline": [item.model_dump() for item in track.timeline],
            "translations": [t.model_dump() for t in track.translations],
            "audio": [a.model_dump() for a in track.audio],
            "qa": {
                "reference_rate": track.qa.reference_rate if track.qa else 0.0,
                "max_drift": track.qa.max_drift if track.qa else 0.0,
                "mean_rate_ratio": track.qa.mean_rate_ratio if track.qa else 0.0,
                "over_budget": track.qa.over_budget_count if track.qa else 0,
                "segments": [s.model_dump() for s in (track.qa.segments if track.qa else [])],
            },
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return [path]
