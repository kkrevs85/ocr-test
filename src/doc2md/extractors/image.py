"""jpeg / png などの画像。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from ..common import Context, Result, SkipFile


def extract(path: Path, ctx: Context) -> Result:
    if not ctx.ocr.enabled:
        raise SkipFile("OCRが無効のため画像は処理しません")
    meta: dict = {"type": "image"}
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        meta["size"] = [im.width, im.height]
        res = ctx.ocr.read(im)
    if res is None:
        return Result("", meta)
    meta["ocr"] = {"images": 1, "lines": res.n_lines, "low_confidence_lines": res.n_low,
                   "mean_score": res.mean_score, "seconds": res.seconds}
    return Result(res.markdown, meta)
