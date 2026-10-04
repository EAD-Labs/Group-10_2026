"""Turn a timed script into segments, cues and resolved time budgets."""

from __future__ import annotations

import os

from ..duration.syllables import count_syllables
from ..schemas import ParsedScript, Segment, Sentence, Violation
from .cues import is_cue_row, parse_cue, to_seconds
from .docx_reader import RawRow, read_script
from .sentences import split_sentences
from .validation import validate_segment


def _stamp(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def _row_time(cell: str) -> float | None:
    cell = cell.strip()
    if not cell:
        return None
    try:
        return to_seconds(cell)
    except (ValueError, IndexError):
        return None


def parse_rows(
    rows: list[RawRow],
    *,
    source: str,
    language: str,
    duration: float | None = None,
) -> ParsedScript:
    narration_rows: list[tuple[float, RawRow]] = []
    cues = []
    cue_owner: dict[str, int] = {}

    for row in rows:
        if is_cue_row(row.time, row.narration):
            cue = parse_cue(row.narration, len(cues) + 1)
            cues.append(cue)
            cue_owner[cue.id] = len(narration_rows) - 1
            continue

        start = _row_time(row.time)
        if start is None:
            # A row with neither a timestamp nor an @ marker continues the row
            # above it (the checklist permits this within a single activity).
            if narration_rows and row.narration.strip():
                _, previous_row = narration_rows[-1]
                previous_row.narration = f"{previous_row.narration} {row.narration}".strip()
                previous_row.bold_terms += row.bold_terms
            continue

        narration_rows.append((start, row))

    if not narration_rows:
        raise ValueError(f"{source}: no timed narration rows found")

    if duration is None:
        # Without the base video we cannot know the tail; give the last row the
        # script's median window.
        windows = sorted(
            narration_rows[i + 1][0] - narration_rows[i][0]
            for i in range(len(narration_rows) - 1)
        )
        median = windows[len(windows) // 2] if windows else 5.0
        duration = narration_rows[-1][0] + median

    segments: list[Segment] = []
    for index, (start, row) in enumerate(narration_rows):
        end = narration_rows[index + 1][0] if index + 1 < len(narration_rows) else duration
        owned = [c for c in cues if cue_owner.get(c.id) == index]

        raw_budget = end - start
        if owned:
            first_cue_at = min(c.at for c in owned)
            reserved = sum(c.clip_duration for c in owned)
            narration_budget = max(first_cue_at - start, 0.0)
            trailing = max(end - first_cue_at - reserved, 0.0)
            # A clip overrunning its window means the script's own numbers
            # disagree; keep budgets sane and let validation report it.
            reserved = min(reserved, max(end - first_cue_at, 0.0))
        else:
            reserved = 0.0
            narration_budget = raw_budget
            trailing = 0.0

        sentences = [
            Sentence(
                index=i,
                text=text,
                char_count=len(text),
                syllables=count_syllables(text),
            )
            for i, text in enumerate(split_sentences(row.narration))
        ]

        segment = Segment(
            id=f"S-{index + 1:03d}",
            index=index,
            start=start,
            end=end,
            raw_budget=raw_budget,
            cue_reserved=reserved,
            narration_budget=narration_budget,
            trailing_slack=trailing,
            text=row.narration,
            char_count=len(row.narration),
            syllables=count_syllables(row.narration),
            sentences=sentences,
            cue_ids=[c.id for c in owned],
            bold_terms=sorted(set(row.bold_terms)),
        )
        segment.violations = validate_segment(segment)
        for cue in owned:
            if cue.reversed_range:
                segment.violations.append(
                    Violation(
                        rule="ST-CUE-ORDER",
                        severity="warning",
                        message=(
                            f"{cue.id}: clip range is written end-first "
                            f"({_stamp(cue.clip_end)} to {_stamp(cue.clip_start)}). "
                            f"Read as {_stamp(cue.clip_start)}-{_stamp(cue.clip_end)}, "
                            f"{cue.clip_duration:.0f}s. Confirm against the source tutorial."
                        ),
                    )
                )
        segments.append(segment)

    return ParsedScript(
        source=source,
        language=language,
        duration=duration,
        segments=segments,
        cues=cues,
    )


def parse_script(path: str, *, language: str, duration: float | None = None) -> ParsedScript:
    return parse_rows(
        read_script(path),
        source=os.path.basename(path),
        language=language,
        duration=duration,
    )
