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
    reversed_range = False
    if len(stamps) >= 2:
        # A reversed range is a typo in the script, not a negative clip, so the
        # two stamps are ordered rather than trusted in the order they were
        # written. This path is real: the client's English and Tamil scripts
        # already disagree on the Bouncing-ball cue (05:44-05:51 against
        # 05:41-05:51), so at least one of these files carries a mistake.
        #
        # The order is corrected but not hidden - reversed_range is reported so
        # the author is told rather than quietly overruled.
        reversed_range = stamps[0] > stamps[1]
        clip_start, clip_end = sorted(stamps[:2])
        duration = clip_end - clip_start

    return ActionCue(
        id=f"C-{index:02d}",
        at=to_seconds(anchor),
        raw=narration.strip(),
        description=remainder,
        clip_start=clip_start,
        clip_end=clip_end,
        clip_duration=duration,
        reversed_range=reversed_range,
    )
