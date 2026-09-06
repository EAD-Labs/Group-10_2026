"""SRT export - real, not a stub.

Subtitles need nothing the pipeline does not already have (placed start, end,
text), so this is one deliverable from HLD S13.1 that is finished today rather
than faked.
"""

from __future__ import annotations

import os

from ..schemas import LanguageTrack


def _timestamp(seconds: float) -> str:
    """Format as SRT's HH:MM:SS,mmm.

    Rounded to whole milliseconds first, then split. Splitting first and
    rounding after lets a value like 59.9996 round its milliseconds up to 1000
    and render as ":60,000", which is not a time and which some players reject
    the whole file over."""
    total_ms = max(int(round(seconds * 1000)), 0)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
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
