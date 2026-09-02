"""Read the raw two-column table out of a .docx timed script.

python-docx is not a dependency: a .docx is a zip containing WordprocessingML,
and we only need paragraph text, table structure and bold runs.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


@dataclass
class RawRow:
    """One table row, before any interpretation."""

    time: str
    narration: str
    bold_terms: list[str] = field(default_factory=list)


def _run_is_bold(run: ET.Element) -> bool:
    props = run.find("w:rPr", NS)
    if props is None:
        return False
    b = props.find("w:b", NS)
    if b is None:
        return False
    # <w:b/> means bold; <w:b w:val="0"/> means explicitly not bold.
    return b.get(f"{{{W}}}val", "1") not in ("0", "false")


def _cell_text_and_bold(cell: ET.Element) -> tuple[str, list[str]]:
    parts: list[str] = []
    bold: list[str] = []
    for para in cell.findall("w:p", NS):
        for run in para.findall("w:r", NS):
            text = "".join(t.text or "" for t in run.findall("w:t", NS))
            if not text:
                continue
            parts.append(text)
            if _run_is_bold(run) and text.strip():
                bold.append(text.strip())
        parts.append("\n")
    joined = "".join(parts)
    # Word splits a phrase across runs freely; stitch adjacent bold fragments.
    merged: list[str] = []
    for term in bold:
        if merged and joined.find(merged[-1] + term) != -1:
            merged[-1] = merged[-1] + term
        else:
            merged.append(term)
    return _clean(joined), [t.strip() for t in merged if t.strip()]


def _clean(text: str) -> str:
    text = text.replace("\u200b", "").replace("\xa0", " ")
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def read_docx_table(path: str) -> list[RawRow]:
    """Return the rows of the first table that looks like a timed script."""
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))

    body = root.find("w:body", NS)
    if body is None:
        raise ValueError(f"{path}: no document body")

    for table in body.iter(f"{{{W}}}tbl"):
        rows: list[RawRow] = []
        for tr in table.findall("w:tr", NS):
            cells = tr.findall("w:tc", NS)
            if len(cells) < 2:
                continue
            time_text, _ = _cell_text_and_bold(cells[0])
            narration, bold = _cell_text_and_bold(cells[1])
            rows.append(RawRow(time=time_text, narration=narration, bold_terms=bold))
        if rows:
            return _drop_header(rows)

    raise ValueError(f"{path}: no table found")


def read_txt(path: str) -> list[RawRow]:
    """Fallback reader for pipe- or tab-separated plain text scripts."""
    rows: list[RawRow] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            sep = "|" if "|" in line else "\t"
            if sep not in line:
                continue
            time_text, narration = line.split(sep, 1)
            rows.append(RawRow(time=_clean(time_text), narration=_clean(narration)))
    return _drop_header(rows)


def _drop_header(rows: list[RawRow]) -> list[RawRow]:
    if rows and rows[0].time.strip().lower() in ("time", "timing", "visual cue"):
        return rows[1:]
    return rows


def read_script(path: str) -> list[RawRow]:
    if path.lower().endswith(".docx"):
        return read_docx_table(path)
    return read_txt(path)
