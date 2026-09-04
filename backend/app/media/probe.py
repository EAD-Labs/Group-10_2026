"""Read a base video's duration out of its container.

The whole timing model hangs off one number - the length of the base video -
and until now it was typed on the command line as `--duration 663.2`. A magic
number nobody can check is a poor foundation for budgets that everything
downstream trusts, so we read it from the file instead.

No ffmpeg. The client's material is WebM, which is EBML: nested elements, each
one a variable-length ID followed by a variable-length size. Duration lives at
Segment > Info > Duration, expressed in TimecodeScale units. That is a few
dozen lines of stdlib, against a toolchain install on every machine that wants
to parse a script - and Module 5 will need ffmpeg for compositing anyway, so
this is not the place to force the dependency.

Handles WebM and Matroska (.webm, .mkv). MP4 renders come later with Module 5;
this deliberately does not guess at them.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

SEGMENT = 0x18538067
INFO = 0x1549A966
TIMECODE_SCALE = 0x2AD7B1
DURATION = 0x4489
MUXING_APP = 0x4D80
WRITING_APP = 0x5741

DEFAULT_TIMECODE_SCALE = 1_000_000  # nanoseconds, per the Matroska spec


@dataclass
class MediaInfo:
    path: str
    duration: float
    """Seconds."""

    timecode_scale: int = DEFAULT_TIMECODE_SCALE
    muxer: str | None = None


def _read_vint(handle, keep_marker: bool) -> tuple[int | None, int]:
    """Read an EBML variable-length integer.

    The leading byte's first set bit says how many bytes long the value is.
    IDs keep that marker bit (it is part of the ID); sizes strip it.
    """
    first = handle.read(1)
    if not first:
        return None, 0
    byte = first[0]
    if byte == 0:  # a valid vint always has a set bit in the first byte
        return None, 1

    length, mask = 1, 0x80
    while not byte & mask:
        mask >>= 1
        length += 1

    value = byte if keep_marker else byte & (mask - 1)
    for extra in handle.read(length - 1):
        value = (value << 8) | extra
    return value, length


def _read_uint(data: bytes) -> int:
    value = 0
    for byte in data:
        value = (value << 8) | byte
    return value


def _read_float(data: bytes) -> float:
    if len(data) == 4:
        return struct.unpack(">f", data)[0]
    if len(data) == 8:
        return struct.unpack(">d", data)[0]
    # Matroska permits an integer-encoded float here; treat it as one.
    return float(_read_uint(data))


def probe(path: str) -> MediaInfo:
    """Return container metadata for a WebM/Matroska file.

    Raises ValueError if the file is missing, or carries no duration - a
    stream-muxed file legitimately may not, and guessing one would put a wrong
    number at the root of every budget.
    """
    if not os.path.exists(path):
        raise ValueError(f"{path}: no such file")

    scale = DEFAULT_TIMECODE_SCALE
    duration: float | None = None
    muxer: str | None = None

    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(0)

        while handle.tell() < size:
            element_id, _ = _read_vint(handle, True)
            length, _ = _read_vint(handle, False)
            if element_id is None or length is None:
                break

            # Segment is the container everything else lives in: step into it
            # rather than over it.
            if element_id == SEGMENT:
                continue

            if element_id == INFO:
                end = handle.tell() + length
                while handle.tell() < end:
                    sub_id, _ = _read_vint(handle, True)
                    sub_length, _ = _read_vint(handle, False)
                    if sub_id is None or sub_length is None:
                        break
                    payload = handle.read(sub_length)
                    if sub_id == TIMECODE_SCALE:
                        scale = _read_uint(payload)
                    elif sub_id == DURATION:
                        duration = _read_float(payload)
                    elif sub_id in (MUXING_APP, WRITING_APP) and muxer is None:
                        muxer = payload.decode("utf-8", "replace")
                break

            handle.seek(length, os.SEEK_CUR)

    if duration is None:
        raise ValueError(f"{path}: no duration in container (not a WebM/Matroska file?)")

    return MediaInfo(
        path=path,
        duration=duration * scale / 1e9,
        timecode_scale=scale,
        muxer=muxer,
    )


def probe_duration(path: str) -> float:
    """The base video's length in seconds."""
    return probe(path).duration
