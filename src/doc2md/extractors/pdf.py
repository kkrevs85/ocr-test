"""PDF。テキスト層のあるページは直接パースし、ないページは画像化してOCRする。"""
from __future__ import annotations

from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

from ..common import Context, Result, SkipFile
from ..tables import pipe_table


def _table_rows(page, table) -> list[list[str]]:
    """罫線から列を、文字の縦位置から行を決めて表を復元する。

    財務諸表のように行の罫線がない表は、標準の表抽出だと1セルに複数行がつぶれるため、
    実セルの位置（結合セルは左端の列）に単語を割り当て、縦位置ごとに1行とする。
    """
    edges: list[float] = []
    for x in sorted({c[0] for c in table.cells} | {c[2] for c in table.cells}):
        if not edges or x - edges[-1] > 3:
            edges.append(x)
    n_cols = max(len(edges) - 1, 1)

    def col_of(word) -> int:
        xc, yc = (word["x0"] + word["x1"]) / 2, (word["top"] + word["bottom"]) / 2
        x = xc
        for c in table.cells:  # 結合セルなら、そのセルの左端の列に入れる
            if c[0] <= xc <= c[2] and c[1] <= yc <= c[3]:
                x = c[0] + 1
                break
        return max(0, min(n_cols - 1, sum(1 for e in edges[1:-1] if x > e - 0.5)))

    words = page.crop(table.bbox).extract_words(x_tolerance=2, y_tolerance=2)
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(round((w["top"] + w["bottom"]) / 2 / 4), []).append(w)
    rows = []
    for key in sorted(lines):
        cells = [""] * n_cols
        for w in sorted(lines[key], key=lambda w: w["x0"]):
            i = col_of(w)
            cells[i] = (cells[i] + " " + w["text"]).strip()
        rows.append(cells)
    return rows


def _direct_page(page, ctx: Context, meta: dict, n: int) -> list[str]:
    blocks: list[tuple[float, str]] = []
    tables = page.find_tables()
    boxes = [t.bbox for t in tables]
    for t in tables:
        rows = _table_rows(page, t)
        if rows:
            blocks.append((t.bbox[1], pipe_table(rows)))
            meta["tables"] += 1

    def outside(obj) -> bool:
        xc, yc = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
        return not any(b[0] <= xc <= b[2] and b[1] <= yc <= b[3] for b in boxes)

    rest = page.filter(lambda o: o.get("object_type") != "char" or outside(o))
    para: list[str] = []
    para_top = prev_bottom = None
    for line in rest.extract_text_lines(x_tolerance=2, y_tolerance=2):
        text = line["text"].strip()
        if not text:
            continue
        if para and line["top"] - prev_bottom > (line["bottom"] - line["top"]) * 0.9:
            blocks.append((para_top, "\n".join(para)))
            para = []
        if not para:
            para_top = line["top"]
        para.append(text)
        prev_bottom = line["bottom"]
    if para:
        blocks.append((para_top, "\n".join(para)))

    pcfg = ctx.config["pdf"]
    if pcfg["ocr_embedded_images"] and ctx.ocr.enabled:
        for k, im in enumerate(page.images, 1):
            if (im["x1"] - im["x0"]) < page.width * pcfg["min_image_ratio"]:
                continue
            bbox = (max(im["x0"], 0), max(im["top"], 0), min(im["x1"], page.width), min(im["bottom"], page.height))
            try:
                pil = page.crop(bbox).to_image(resolution=pcfg["dpi"]).original
                block = ctx.ocr_image_block(pil, f"ページ{n}の画像{k}", meta)
                if block:
                    blocks.append((im["top"], block))
            except Exception as e:
                meta.setdefault("warnings", []).append(f"ページ{n}の画像{k}を読めません: {e}")
    return [b for _, b in sorted(blocks, key=lambda x: x[0])]


def extract(path: Path, ctx: Context) -> Result:
    try:
        pdf = pdfplumber.open(str(path))
    except Exception as e:
        if "password" in type(e).__name__.lower() or "password" in str(e).lower() or "encrypt" in str(e).lower():
            raise SkipFile("開くのにパスワードが必要なPDFは対象外です") from e
        raise
    meta: dict = {"type": "pdf", "pages": len(pdf.pages), "direct_pages": 0, "ocr_pages": 0, "tables": 0}
    out: list[str] = []
    raster = None
    with pdf:
        for n, page in enumerate(pdf.pages, 1):
            out.append(f"## ページ {n}")
            n_chars = sum(1 for c in page.chars if c["text"].strip())
            if n_chars >= ctx.config["pdf"]["min_text_chars"]:
                meta["direct_pages"] += 1
                out += _direct_page(page, ctx, meta, n)
                continue
            meta["ocr_pages"] += 1
            if not ctx.ocr.enabled:
                out.append("（テキスト層がなく、OCRが無効のため未処理）")
                continue
            if raster is None:
                raster = pdfium.PdfDocument(str(path))
            pil = raster[n - 1].render(scale=ctx.config["pdf"]["dpi"] / 72).to_pil()
            res = ctx.ocr.read(pil)
            if res is not None:
                stats = meta.setdefault("ocr", {"images": 0, "lines": 0, "low_confidence_lines": 0, "seconds": 0.0})
                stats["images"] += 1
                stats["lines"] += res.n_lines
                stats["low_confidence_lines"] += res.n_low
                stats["seconds"] = round(stats["seconds"] + res.seconds, 2)
                if res.n_low:
                    meta.setdefault("low_confidence_pages", []).append(n)
                if res.markdown:
                    out.append(res.markdown)
    return Result("\n\n".join(out), meta)
