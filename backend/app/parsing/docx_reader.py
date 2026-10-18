"""Read the raw two-column table out of a timed script.

Word (.docx) and LibreOffice (.odt) scripts are both zips of XML, and we only
need paragraph text, table structure and bold runs, so neither python-docx nor
odfpy is a dependency.

The format is sniffed from the zip's contents, not trusted from the name:
three of the client's LibreOffice Writer scripts are .odt files saved with a
.docx extension.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}

ODF_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
ODF_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
ODF_STYLE = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
ODF_FO = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"


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
    return _finish("".join(parts), bold)


def _finish(joined: str, bold: list[str]) -> tuple[str, list[str]]:
    # Editors split a phrase across runs freely; stitch adjacent bold fragments.
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


def _odt_bold_styles(root: ET.Element) -> set[str]:
    """Names of the automatic styles that make text bold.

    ODF does not mark a span bold directly; the span names a style, and the
    style's text properties carry the weight."""
    bold = set()
    for style in root.iter(f"{{{ODF_STYLE}}}style"):
        props = style.find(f"{{{ODF_STYLE}}}text-properties")
        if props is not None and props.get(f"{{{ODF_FO}}}font-weight") in ("bold", "600", "700", "800", "900"):
            bold.add(style.get(f"{{{ODF_STYLE}}}name"))
    return bold


def _odt_cell_text_and_bold(cell: ET.Element, bold_styles: set[str]) -> tuple[str, list[str]]:
    parts: list[str] = []
    bold: list[str] = []

    def add(text: str | None, is_bold: bool) -> None:
        if not text:
            return
        parts.append(text)
        if is_bold and text.strip():
            bold.append(text.strip())

    def walk(element: ET.Element, is_bold: bool) -> None:
        add(element.text, is_bold)
        for child in element:
            if child.tag == f"{{{ODF_TEXT}}}s":  # run of spaces
                parts.append(" " * int(child.get(f"{{{ODF_TEXT}}}c", "1")))
            elif child.tag in (f"{{{ODF_TEXT}}}tab", f"{{{ODF_TEXT}}}line-break"):
                parts.append(" ")
            else:
                styled = child.get(f"{{{ODF_TEXT}}}style-name") in bold_styles
                walk(child, is_bold or styled)
            add(child.tail, is_bold)

    for para in cell.iter(f"{{{ODF_TEXT}}}p"):
        walk(para, para.get(f"{{{ODF_TEXT}}}style-name") in bold_styles)
        parts.append("\n")
    return _finish("".join(parts), bold)


def read_odt_table(path: str) -> list[RawRow]:
    """Return the rows of the first table in an OpenDocument text file."""
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("content.xml"))
        try:
            styles = ET.fromstring(archive.read("styles.xml"))
        except KeyError:
            styles = None
    bold_styles = _odt_bold_styles(root) | (_odt_bold_styles(styles) if styles is not None else set())

    for table in root.iter(f"{{{ODF_TABLE}}}table"):
        rows: list[RawRow] = []
        for tr in table.iter(f"{{{ODF_TABLE}}}table-row"):
            cells = tr.findall(f"{{{ODF_TABLE}}}table-cell")
            if len(cells) < 2:
                continue
            time_text, _ = _odt_cell_text_and_bold(cells[0], bold_styles)
            narration, bold = _odt_cell_text_and_bold(cells[1], bold_styles)
            rows.append(RawRow(time=time_text, narration=narration, bold_terms=bold))
        if rows:
            return _drop_header(rows)

    raise ValueError(f"{path}: no table found")


def script_format(path: str) -> str:
    """'docx', 'odt' or 'txt', judged by content: the extension is not reliable."""
    if not zipfile.is_zipfile(path):
        return "txt"
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    if "word/document.xml" in names:
        return "docx"
    if "content.xml" in names:
        return "odt"
    raise ValueError(f"{path}: a zip, but neither a Word nor an OpenDocument file")


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


SCRIPT_EXTENSIONS = (".docx", ".odt", ".txt")


def read_script(path: str) -> list[RawRow]:
    kind = script_format(path)
    if kind == "docx":
        return read_docx_table(path)
    if kind == "odt":
        return read_odt_table(path)
    return read_txt(path)
