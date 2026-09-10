"""Timeline assembly - minimal placement, pending Step 3.

Today: each narration clip is anchored at its segment's start time on the base
video, which is what the timed script says and what the client's editors do by
hand.

Not yet done, and deliberately left as Step 3's job:
  * hold insertion at non-action gaps (the parser already knows which gaps
    qualify - trailing_slack is free, cue_reserved is not)
  * re-flowing subsequent items when a clip overruns its window

The QA report measures the consequences of not doing those things, so the gap
shows up as numbers rather than as a silent assumption.
"""

from __future__ import annotations

from ..schemas import AlignmentResult, AudioAsset, ParsedScript, TimelineItem


def build_timeline(
    script: ParsedScript,
    audio: list[AudioAsset],
    alignments: list[AlignmentResult] | None = None,
) -> list[TimelineItem]:
    by_segment = {a.segment_id: a for a in audio}
    aligned = {a.segment_id: a for a in (alignments or [])}

    items: list[TimelineItem] = []
    for segment in script.segments:
        asset = by_segment.get(segment.id)
        if asset is None:
            continue
        alignment = aligned.get(segment.id)
        length = alignment.speech_duration if alignment else asset.duration
        items.append(
            TimelineItem(
                segment_id=segment.id,
                start=segment.start,
                end=segment.start + length,
                audio_path=asset.path,
                hold_after=0.0,  # Step 3
                # A cue in this window means an embedded clip is already using
                # the space: the boundary is frame-locked and nothing may be
                # inserted after this item.
                anchored=bool(segment.cue_ids),
            )
        )
    return items
