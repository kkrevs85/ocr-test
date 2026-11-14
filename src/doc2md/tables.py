"""表のMarkdown化。結合セルがなければパイプ表、あればHTML表にする。"""
from __future__ import annotations

import html


def _cell(text: object) -> str:
    s = "" if text is None else str(text)
    return s.replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>").strip()


def pipe_table(rows: list[list[object]]) -> str:
    rows = [r for r in rows if r is not None]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [[_cell(c) for c in r] + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(norm[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return "\n".join(out)


def html_table(rows: list[list[object]], spans: dict[tuple[int, int], tuple[int, int]],
               covered: set[tuple[int, int]]) -> str:
    """spans[(r, c)] = (rowspan, colspan)。covered は結合で隠れるセル。"""
    out = ["<table>"]
    for r, row in enumerate(rows):
        cells = []
        for c, val in enumerate(row):
            if (r, c) in covered:
                continue
            rs, cs = spans.get((r, c), (1, 1))
            attr = (f' rowspan="{rs}"' if rs > 1 else "") + (f' colspan="{cs}"' if cs > 1 else "")
            tag = "th" if r == 0 else "td"
            text = html.escape("" if val is None else str(val)).replace("\n", "<br>")
            cells.append(f"<{tag}{attr}>{text}</{tag}>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def render_table(rows: list[list[object]], spans: dict[tuple[int, int], tuple[int, int]] | None = None) -> str:
    spans = {k: v for k, v in (spans or {}).items() if v != (1, 1)}
    if not spans:
        return pipe_table(rows)
    covered: set[tuple[int, int]] = set()
    for (r, c), (rs, cs) in spans.items():
        for dr in range(rs):
            for dc in range(cs):
                if (dr, dc) != (0, 0):
                    covered.add((r + dr, c + dc))
    return html_table(rows, spans, covered)


def spans_from_ids(ids: list[list[object]]) -> dict[tuple[int, int], tuple[int, int]]:
    """同じIDが並ぶセルを結合とみなし spans を作る（docx 用）。"""
    spans: dict[tuple[int, int], tuple[int, int]] = {}
    seen: set[tuple[int, int]] = set()
    for r, row in enumerate(ids):
        for c, ident in enumerate(row):
            if (r, c) in seen:
                continue
            cs = 1
            while c + cs < len(row) and row[c + cs] is ident:
                cs += 1
            rs = 1
            while r + rs < len(ids) and c < len(ids[r + rs]) and ids[r + rs][c] is ident:
                rs += 1
            for dr in range(rs):
                for dc in range(cs):
                    seen.add((r + dr, c + dc))
            spans[(r, c)] = (rs, cs)
    return spans
