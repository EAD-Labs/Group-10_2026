"""SRT export - real, not a stub.

Subtitles need nothing the pipeline does not already have (placed start, end,
text), so this is one deliverable from HLD S13.1 that is finished today rather
than faked.
"""

from __future__ import annotations

import os

from ..schemas import LanguageTrack


def _timestamp(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:  # rounding crossed a second boundary
        millis, secs = 0, secs + 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


class SrtExporter:
    name = "srt"

    def export(self, track: LanguageTrack, out_dir: str) -> list[str]:
        by_segment = {t.segment_id: t for t in track.translations}
        path = os.path.join(out_dir, f"{track.language}.srt")
        os.makedirs(out_dir, exist_ok=True)

        lines: list[str] = []
        for number, item in enumerate(track.timeline, start=1):
            translated = by_segment.get(item.segment_id)
            if translated is None or not translated.text.strip():
                continue
            lines.append(str(number))
            lines.append(f"{_timestamp(item.start)} --> {_timestamp(item.end)}")
            lines.append(translated.text.strip())
            lines.append("")

        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        return [path]
