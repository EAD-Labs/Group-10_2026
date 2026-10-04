"""Build a side-by-side translation review page.

    python -m app.review --project out/ta/ta-project.json \
                         --reference ../Tamil-script-sample.docx \
                         --out out/review.html

This is HLD S9.1's Translation Review screen as a static file: source and
translation side by side with their durations, escalations called out, and -
when a reference translation exists - the human's version in the same row.

That third column is the point. The client has a professional Tamil track for
this tutorial, so the question is not "did the model produce Tamil" but "did it
say the same thing in fewer aksharas than the human needed". This page is where
that is answered segment by segment.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys

from .parsing.parser import parse_script


def _rows(project: dict, reference: dict[str, str] | None) -> list[dict]:
    qa = {row["segment_id"]: row for row in project.get("qa", {}).get("segments", [])}
    out = []
    for item in project.get("translations", []):
        segment_id = item["segment_id"]
        measured = qa.get(segment_id, {})
        out.append(
            {
                "id": segment_id,
                "source": item.get("source_text", ""),
                "text": item.get("text", ""),
                "human": (reference or {}).get(segment_id, ""),
                "budget": item.get("budget", 0.0),
                "predicted": item.get("predicted_duration", 0.0),
                "units": item.get("syllables", 0),
                "attempts": item.get("attempts", 0),
                "fitted": item.get("fitted", False),
                "note": item.get("note") or "",
                "pause": measured.get("pause_after", 0.0),
            }
        )
    return out


CSS = """
:root { --ink:#1a1a1a; --muted:#666; --line:#e3e3e3; --ok:#e8f5e9; --bad:#fdecea;
        --okb:#43a047; --badb:#e53935; --bg:#fafafa; }
* { box-sizing:border-box; }
body { margin:0; padding:24px; background:var(--bg); color:var(--ink);
       font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; }
h1 { font-size:20px; margin:0 0 4px; }
.sub { color:var(--muted); margin-bottom:20px; }
.cards { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; }
.card { background:#fff; border:1px solid var(--line); border-radius:8px;
        padding:12px 16px; min-width:130px; }
.card .n { font-size:22px; font-weight:600; }
.card .l { color:var(--muted); font-size:12px; }
table { width:100%; border-collapse:collapse; background:#fff;
        border:1px solid var(--line); border-radius:8px; overflow:hidden; }
th { text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:.04em;
     color:var(--muted); padding:10px 12px; border-bottom:1px solid var(--line);
     background:#f5f5f5; }
td { padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }
tr:last-child td { border-bottom:none; }
tr.bad { background:var(--bad); }
tr.ok  { background:var(--ok); }
.id { font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12px;
      color:var(--muted); white-space:nowrap; }
.num { font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12px;
       white-space:nowrap; }
.tag { display:inline-block; padding:1px 7px; border-radius:10px; font-size:11px;
       font-weight:600; color:#fff; }
.tag.y { background:var(--okb); } .tag.n { background:var(--badb); }
.note { color:var(--badb); font-size:12px; margin-top:4px; }
.win { color:var(--okb); font-weight:600; }
@media (max-width:760px){ body{padding:12px;} td,th{padding:8px;} }
"""


def build_html(project: dict, rows: list[dict], has_reference: bool) -> str:
    fitted = sum(1 for r in rows if r["fitted"])
    escalated = len(rows) - fitted
    shorter = sum(1 for r in rows if r["human"] and r["units"] < _count(r["human"]))
    comparable = sum(1 for r in rows if r["human"])

    cards = [
        ("segments", len(rows)),
        ("fitted", fitted),
        ("need an author", escalated),
    ]
    if comparable:
        cards.append(("shorter than human", f"{shorter}/{comparable}"))

    head = "".join(
        f'<div class="card"><div class="n">{value}</div>'
        f'<div class="l">{label}</div></div>'
        for label, value in cards
    )

    columns = ["", "budget", "English source", "generated"]
    if has_reference:
        columns.append("human reference")
    columns.append("fits")

    body = []
    for row in rows:
        human_units = _count(row["human"]) if row["human"] else 0
        win = (
            ' <span class="win">&minus;'
            f'{human_units - row["units"]}</span>'
            if human_units and row["units"] < human_units
            else ""
        )
        cells = [
            f'<td class="id">{html.escape(row["id"])}</td>',
            f'<td class="num">{row["budget"]:.1f}s<br>'
            f'<span style="color:#888">{row["predicted"]:.1f}s used</span></td>',
            f'<td>{html.escape(row["source"])}</td>',
            f'<td>{html.escape(row["text"]) or "<em>&mdash;</em>"}'
            f'<div class="num" style="color:#888">{row["units"]} aksharas'
            f'{" &middot; " + str(row["attempts"]) + " attempt(s)" if row["attempts"] else ""}'
            f"{win}</div>"
            + (f'<div class="note">{html.escape(row["note"])}</div>' if row["note"] else "")
            + "</td>",
        ]
        if has_reference:
            cells.append(
                f'<td>{html.escape(row["human"])}'
                + (
                    f'<div class="num" style="color:#888">{human_units} aksharas</div>'
                    if human_units
                    else ""
                )
                + "</td>"
            )
        tag = '<span class="tag y">yes</span>' if row["fitted"] else '<span class="tag n">no</span>'
        cells.append(f"<td>{tag}</td>")
        body.append(
            f'<tr class="{"ok" if row["fitted"] else "bad"}">' + "".join(cells) + "</tr>"
        )

    language = project.get("language", "")
    source = project.get("source", "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Translation review - {html.escape(language)}</title>
<style>{CSS}</style></head><body>
<h1>Translation review &mdash; {html.escape(language)}</h1>
<div class="sub">{html.escape(source)} &middot; duration {project.get('duration', 0):.1f}s
&middot; budgets are speaking budgets (window less the reserved pause)</div>
<div class="cards">{head}</div>
<table><thead><tr>{''.join(f'<th>{c}</th>' for c in columns)}</tr></thead>
<tbody>{''.join(body)}</tbody></table>
</body></html>"""


def _count(text: str) -> int:
    from .duration.syllables import count_syllables

    return count_syllables(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a translation review page.")
    parser.add_argument("--project", required=True, help="<lang>-project.json from a run")
    parser.add_argument("--reference", default=None, help="human-translated script, optional")
    parser.add_argument("--out", default=None, help="output .html path")
    args = parser.parse_args(argv)

    with open(args.project, encoding="utf-8") as handle:
        project = json.load(handle)

    reference = None
    if args.reference:
        script = parse_script(args.reference, language=project.get("language", "ta"))
        reference = {segment.id: segment.text for segment in script.segments}

    rows = _rows(project, reference)
    out_path = args.out or os.path.join(
        os.path.dirname(args.project), f"{project.get('language', 'track')}-review.html"
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(build_html(project, rows, bool(reference)))

    fitted = sum(1 for r in rows if r["fitted"])
    print(f"  {len(rows)} segments, {fitted} fitted, {len(rows) - fitted} escalated")
    print(f"  wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
