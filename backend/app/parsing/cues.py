"""Detection and parsing of action-cue rows.

A cue row has an empty Time cell and a narration cell beginning with "@MM:SS".
It tells the editor to splice audio from another tutorial into the base video:

    @04:56 Add the audio of Bouncing ball tutorial from 05:44 to 05:51
    @09:00- Add the Audio of Rocket Animation from 03:10 to 03:20

The Tamil edition of the same script writes the clip range first, in Tamil word
order, so we do not pattern-match on "from ... to ...".  We take the anchor from
the leading @, then read the first two timestamps that follow it, whatever
language surrounds them.
"""

from __future__ import annotations

import re

from ..schemas import ActionCue

TIMESTAMP = re.compile(r"(\d{1,3}):([0-5]\d)")
ANCHOR = re.compile(r"^\s*@\s*(\d{1,3}:[0-5]\d)\s*[-\u2013]?\s*(.*)$", re.S)


def to_seconds(stamp: str) -> float:
    minutes, seconds = stamp.split(":")
    return int(minutes) * 60 + int(seconds)


def is_cue_row(time_cell: str, narration: str) -> bool:
    """A cue row is identified by the @ marker, not merely by a blank time
    cell - a blank cell alone may just be a continuation row."""
    return not time_cell.strip() and narration.lstrip().startswith("@")


def parse_cue(narration: str, index: int) -> ActionCue:
    match = ANCHOR.match(narration)
    if not match:
        raise ValueError(f"not a cue row: {narration!r}")

    anchor, remainder = match.group(1), match.group(2).strip()
    stamps = [to_seconds(f"{m.group(1)}:{m.group(2)}") for m in TIMESTAMP.finditer(remainder)]

    clip_start = clip_end = None
    duration = 0.0
    if len(stamps) >= 2:
        clip_start, clip_end = stamps[0], stamps[1]
        if clip_end > clip_start:
            duration = clip_end - clip_start
        else:
            # Defensive: a reversed range is a script typo, not a negative clip.
            clip_start, clip_end = clip_end, clip_start
            duration = clip_start - clip_end if clip_start > clip_end else 0.0

    return ActionCue(
        id=f"C-{index:02d}",
        at=to_seconds(anchor),
        raw=narration.strip(),
        description=remainder,
        clip_start=clip_start,
        clip_end=clip_end,
        clip_duration=duration,
    )
