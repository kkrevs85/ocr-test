"""xlsx。シートごとに使用範囲を表にし、結合セル・表示形式・埋め込み画像・グラフを扱う。"""
from __future__ import annotations

import datetime as dt
import io
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from PIL import Image

from ..common import Context, Result, SkipFile
from ..tables import pipe_table, render_table

_C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def format_value(cell) -> str:
    """セルの値を、表示形式（桁区切り・％・△・日付）に沿った文字列にする。"""
    v = cell.value
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time(0) else v.isoformat(sep=" ", timespec="minutes")
    if isinstance(v, (dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (int, float)):
        nf = cell.number_format or "General"
        sections = nf.split(";")
        pos = sections[0]
        m = re.search(r"\.(0+)", pos)
        dec = len(m.group(1)) if m else 0
        if "%" in pos:
            return f"{v * 100:.{dec}f}%"
        if "#,#" in pos or "0,0" in pos:
            neg = sections[1] if len(sections) > 1 else ""
            if v < 0 and ("△" in neg or "▲" in neg):
                return ("△" if "△" in neg else "▲") + f"{abs(v):,.{dec}f}"
            if v < 0 and "(" in neg:
                return f"({abs(v):,.{dec}f})"
            return f"{v:,.{dec}f}"
        if m:
            return f"{v:.{dec}f}"
        if isinstance(v, float):
            return str(int(v)) if v.is_integer() else f"{round(v, 10):g}" if abs(v) < 1e15 else str(v)
        return str(v)
    return str(v).strip()


def _sheet_table(ws) -> tuple[str, int]:
    cells = [(c.row, c.column) for row in ws.iter_rows() for c in row if c.value is not None]
    if not cells:
        return "", 0
    r0, r1 = min(r for r, _ in cells), max(r for r, _ in cells)
    c0, c1 = min(c for _, c in cells), max(c for _, c in cells)
    merges = [m for m in ws.merged_cells.ranges
              if m.min_row >= r0 and m.max_row <= r1 and m.min_col >= c0 and m.max_col <= c1]
    grid = [[format_value(ws.cell(r, c)) for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]
    if merges:
        spans = {(m.min_row - r0, m.min_col - c0): (m.max_row - m.min_row + 1, m.max_col - m.min_col + 1)
                 for m in merges}
        return render_table(grid, spans), len(grid)
    keep_rows = [r for r in grid if any(r)]
    keep_cols = [i for i in range(len(grid[0])) if any(r[i] for r in keep_rows)]
    rows = [[r[i] for i in keep_cols] for r in keep_rows]
    return pipe_table(rows), len(rows)


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if path not in z.namelist():
        return {}
    out = {}
    for rel in ET.fromstring(z.read(path)):
        target = rel.get("Target", "")
        full = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
            posixpath.join(posixpath.dirname(part), target))
        out[rel.get("Id")] = (rel.get("Type", "").rsplit("/", 1)[-1], full)
    return out


def _chart_markdown(xml: bytes) -> str:
    root = ET.fromstring(xml)
    title_el = root.find(f".//{_C}title")
    title = "".join(t.text or "" for t in title_el.iter(f"{_A}t")).strip() if title_el is not None else ""
    series = []
    for ser in root.iter(f"{_C}ser"):
        name = "".join(v.text or "" for v in ser.findall(f"{_C}tx//{_C}v")).strip()
        cats = [v.text or "" for v in ser.findall(f"{_C}cat//{_C}pt/{_C}v")]
        vals = [v.text or "" for v in ser.findall(f"{_C}val//{_C}pt/{_C}v")]
        ref = "".join(v.text or "" for v in ser.findall(f"{_C}val//{_C}f"))
        series.append((name, cats, vals, ref))
    parts = [f"**[グラフ] {title}**" if title else "**[グラフ]**"]
    if series and not any(s[2] for s in series):
        refs = ", ".join(s[3] for s in series if s[3])
        parts.append(f"（グラフの値はファイルに保存されていません。参照範囲: {refs}）" if refs else "（値なし）")
    elif series:
        cats = max((s[1] for s in series), key=len)
        n = max(len(cats), max(len(s[2]) for s in series))
        rows = [["項目"] + [s[0] or f"系列{i + 1}" for i, s in enumerate(series)]]
        for i in range(n):
            rows.append([cats[i] if i < len(cats) else str(i + 1)] + [s[2][i] if i < len(s[2]) else "" for s in series])
        parts.append(pipe_table(rows))
    return "\n\n".join(parts)


def _charts_by_sheet(path: Path) -> dict[str, list[str]]:
    """シート名 -> グラフのMarkdown。openpyxl は読み込み時にグラフを保持しないためXMLを直接読む。"""
    out: dict[str, list[str]] = {}
    try:
        with zipfile.ZipFile(path) as z:
            wb_rels = _rels(z, "xl/workbook.xml")
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            for sheet in wb.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"):
                rel = wb_rels.get(sheet.get(f"{_R}id"))
                if not rel:
                    continue
                for kind, drawing in _rels(z, rel[1]).values():
                    if kind != "drawing":
                        continue
                    for kind2, chart in _rels(z, drawing).values():
                        if kind2 == "chart" and chart in z.namelist():
                            out.setdefault(sheet.get("name"), []).append(_chart_markdown(z.read(chart)))
    except Exception:
        pass
    return out


def extract(path: Path, ctx: Context) -> Result:
    try:
        wb = load_workbook(str(path), data_only=True)
    except zipfile.BadZipFile as e:
        raise SkipFile("xlsxとして開けません（パスワード付き、または破損）") from e
    charts = _charts_by_sheet(path)
    meta: dict = {"type": "xlsx", "sheets": [], "images": 0, "charts": sum(len(v) for v in charts.values())}
    out: list[str] = []
    for ws in wb.worksheets:
        hidden = ws.sheet_state != "visible"
        if hidden and not ctx.config["office"]["include_hidden_sheets"]:
            continue
        out.append(f"## シート：{ws.title}" + ("（非表示）" if hidden else ""))
        table, n_rows = _sheet_table(ws)
        meta["sheets"].append({"name": ws.title, "rows": n_rows, "hidden": hidden})
        if table:
            out.append(table)
        for img in getattr(ws, "_images", []):
            meta["images"] += 1
            if not ctx.config["office"]["ocr_embedded_images"]:
                continue
            try:
                marker = img.anchor._from
                pos = f"{get_column_letter(marker.col + 1)}{marker.row + 1}"
            except Exception:
                pos = "位置不明"
            try:
                im = Image.open(io.BytesIO(img._data()))
                block = ctx.ocr_image_block(im, f"セル{pos}付近の画像", meta)
                if block:
                    out.append(block)
            except Exception as e:
                meta.setdefault("warnings", []).append(f"シート{ws.title}の画像を読めません: {e}")
        out += charts.get(ws.title, [])
    return Result("\n\n".join(out), meta)
