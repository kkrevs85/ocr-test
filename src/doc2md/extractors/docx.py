"""docx。見出し・段落・表を文書順に取り出し、埋め込み画像はOCRする。"""
from __future__ import annotations

import io
import re
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from PIL import Image

from ..common import Context, Result
from ..tables import render_table, spans_from_ids

_BLIP = ("{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"


def _heading_level(style_name: str) -> int | None:
    name = (style_name or "").lower()
    if name == "title" or name == "表題":
        return 1
    m = re.match(r"(heading|見出し)\s*(\d)", name)
    return min(int(m.group(2)) + 1, 6) if m else None


def _images(element, part, ctx: Context, meta: dict, counter: list[int]) -> list[str]:
    blocks = []
    if not ctx.config["office"]["ocr_embedded_images"]:
        return blocks
    for blip in element.iter(_BLIP):
        rid = blip.get(_EMBED)
        if not rid or rid not in part.related_parts:
            continue
        counter[0] += 1
        try:
            im = Image.open(io.BytesIO(part.related_parts[rid].blob))
            block = ctx.ocr_image_block(im, f"画像{counter[0]}", meta)
        except Exception as e:  # 壊れた画像やEMFなど
            meta.setdefault("warnings", []).append(f"画像{counter[0]}を読めません: {e}")
            continue
        if block:
            blocks.append(block)
    return blocks


def extract(path: Path, ctx: Context) -> Result:
    doc = Document(str(path))
    meta: dict = {"type": "docx", "tables": 0}
    out: list[str] = []
    counter = [0]
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = p.text.strip()
            if text:
                style = p.style.name if p.style is not None else ""
                level = _heading_level(style)
                if level:
                    out.append("#" * level + " " + text)
                elif "list" in style.lower() or "箇条書き" in style or child.find(".//{*}numPr") is not None:
                    out.append("- " + text)
                else:
                    out.append(text)
            out += _images(child, doc.part, ctx, meta, counter)
        elif tag == "tbl":
            table = Table(child, doc)
            ids = [[c._tc for c in row.cells] for row in table.rows]
            rows = [[c.text.strip() for c in row.cells] for row in table.rows]
            if rows:
                out.append(render_table(rows, spans_from_ids(ids)))
                meta["tables"] += 1
            out += _images(child, doc.part, ctx, meta, counter)
    meta["images"] = counter[0]
    # 連続する箇条書きは空行を挟まない
    md = "\n\n".join(out)
    md = re.sub(r"(\n- [^\n]*)\n\n(?=- )", r"\1\n", "\n" + md).lstrip("\n")
    return Result(md, meta)
