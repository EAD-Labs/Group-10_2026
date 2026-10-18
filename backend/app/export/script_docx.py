"""The dubbed script: the English script's own table, in the target language.

The client writes and receives scripts as a two-column Word table - Time |
Narration - with on-screen terms in bold (samples/Tamil-script-sample.docx).
This exporter hands the translation back in that same shape, so it can be
reviewed, corrected and archived like any human-made script:

    <lang>-script.docx    Time | Narration, one row per English row,
                          protected terms kept in bold

Written with the standard library (a .docx is a zip of XML), so it adds no
dependency. The narration is what the voice actually spoke - the fitted text,
not the first machine draft.
"""

from __future__ import annotations

import os
import re
import zipfile
from xml.sax.saxutils import escape

from ..schemas import LanguageTrack, ParsedScript

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_BORDER = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
_BORDERS = "".join(_BORDER.format(side) for side in ("top", "left", "bottom", "right", "insideH", "insideV"))


def clock(seconds: float) -> str:
    """mm:ss, as the client's scripts write it (h:mm:ss past an hour)."""
    total = max(int(round(seconds)), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _runs(text: str, bold_terms: list[str]) -> str:
    """The text as Word runs, with every occurrence of a bold term in bold."""
    terms = sorted({t.strip(" .,:;") for t in bold_terms if t.strip(" .,:;")}, key=len, reverse=True)
    parts = re.split("(" + "|".join(map(re.escape, terms)) + ")", text) if terms else [text]
    out = []
    for part in parts:
        if not part:
            continue
        props = "<w:rPr><w:b/></w:rPr>" if part in terms else ""
        out.append(f'<w:r>{props}<w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return "".join(out)


def _cell(runs: str, width: int) -> str:
    return f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr><w:p>{runs}</w:p></w:tc>'


def _row(time: str, runs: str) -> str:
    return f"<w:tr>{_cell(time, 1300)}{_cell(runs, 8000)}</w:tr>"


def document_xml(rows: list[tuple[str, str, list[str]]], title: str) -> str:
    """rows: (time, narration, bold terms)."""
    bold = lambda text: f'<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'  # noqa: E731
    plain = lambda text: f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'  # noqa: E731
    body = [_row(bold("Time"), bold("Narration"))]
    body += [_row(plain(time), _runs(text, terms)) for time, text, terms in rows]
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{_W}"><w:body>'
        f"<w:p>{bold(title)}</w:p>"
        f'<w:tbl><w:tblPr><w:tblW w:w="9300" w:type="dxa"/><w:tblBorders>{_BORDERS}</w:tblBorders></w:tblPr>'
        f'<w:tblGrid><w:gridCol w:w="1300"/><w:gridCol w:w="8000"/></w:tblGrid>{"".join(body)}</w:tbl>'
        "<w:sectPr/></w:body></w:document>"
    )


def write_docx(path: str, rows: list[tuple[str, str, list[str]]], title: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document_xml(rows, title))


class ScriptExporter:
    name = "script"

    def __init__(self, script: ParsedScript | None = None) -> None:
        self.script = script

    def export(self, track: LanguageTrack, out_dir: str) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        by_segment = {t.segment_id: t for t in track.translations}
        segments = self.script.segments if self.script else []
        rows = []
        for segment in segments:
            translated = by_segment.get(segment.id)
            if translated is None:
                continue
            terms = [t for t in segment.bold_terms if t in translated.text]
            rows.append((clock(segment.start), translated.text.strip(), terms))
        if not segments:  # no script to hand: fall back to the track's own order
            rows = [(t.segment_id, t.text.strip(), []) for t in track.translations]
        title = f"{os.path.splitext(os.path.basename(track.source))[0]} ({track.language})"
        path = os.path.join(out_dir, f"{track.language}-script.docx")
        write_docx(path, rows, title)
        return [path]
