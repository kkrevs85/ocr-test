"""pptx。スライドごとにタイトル・本文・表・グラフ・ノートを取り出し、画像はOCRする。"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from ..common import Context, Result
from ..tables import pipe_table, render_table


def _walk(shapes):
    for sh in shapes:
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _walk(sh.shapes)
        else:
            yield sh


def _text_frame(tf) -> str:
    lines = []
    for p in tf.paragraphs:
        text = "".join(r.text for r in p.runs).strip() or p.text.strip()
        if text:
            lines.append(("  " * p.level + "- " + text) if p.level > 0 else text)
    return "\n".join(lines)


def _table(tbl) -> str:
    rows, spans = [], {}
    for r, row in enumerate(tbl.rows):
        cells = []
        for c, cell in enumerate(row.cells):
            cells.append(cell.text.strip())
            if cell.is_merge_origin:
                spans[(r, c)] = (cell.span_height, cell.span_width)
        rows.append(cells)
    return render_table(rows, spans)


def _chart(chart) -> str:
    parts = []
    try:
        if chart.has_title:
            parts.append(f"**[グラフ] {chart.chart_title.text_frame.text.strip()}**")
        plot = chart.plots[0]
        cats = [str(c) for c in plot.categories]
        rows = [["項目"] + [s.name or f"系列{i + 1}" for i, s in enumerate(plot.series)]]
        for i, cat in enumerate(cats):
            rows.append([cat] + [("" if s.values[i] is None else f"{s.values[i]:g}") for s in plot.series])
        parts.append(pipe_table(rows))
    except Exception:
        parts.append("**[グラフ]**（データを読み取れませんでした）")
    return "\n\n".join(parts)


def extract(path: Path, ctx: Context) -> Result:
    prs = Presentation(str(path))
    meta: dict = {"type": "pptx", "slides": len(prs.slides), "tables": 0, "images": 0}
    out: list[str] = []
    for n, slide in enumerate(prs.slides, 1):
        title_shape = slide.shapes.title
        title = title_shape.text_frame.text.strip() if title_shape is not None and title_shape.has_text_frame else ""
        out.append(f"## スライド {n}" + (f"：{title}" if title else ""))
        shapes = sorted(_walk(slide.shapes), key=lambda s: ((s.top or 0), (s.left or 0)))
        for sh in shapes:
            if title_shape is not None and sh.shape_id == title_shape.shape_id:
                continue
            if getattr(sh, "has_table", False) and sh.has_table:
                out.append(_table(sh.table))
                meta["tables"] += 1
            elif getattr(sh, "has_chart", False) and sh.has_chart:
                out.append(_chart(sh.chart))
            elif sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                meta["images"] += 1
                if ctx.config["office"]["ocr_embedded_images"]:
                    try:
                        im = Image.open(io.BytesIO(sh.image.blob))
                        block = ctx.ocr_image_block(im, f"スライド{n}の画像", meta)
                        if block:
                            out.append(block)
                    except Exception as e:
                        meta.setdefault("warnings", []).append(f"スライド{n}の画像を読めません: {e}")
            elif sh.has_text_frame:
                text = _text_frame(sh.text_frame)
                if text:
                    out.append(text)
        if ctx.config["office"]["include_notes"] and slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                out.append("**[ノート]**\n\n" + notes)
    return Result("\n\n".join(out), meta)
