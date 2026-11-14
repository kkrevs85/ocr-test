"""共通の型と設定読み込み。"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "output_root": "output",
    "ocr": {
        "enabled": True, "lang": "japan", "detection_model": "", "recognition_model": "",
        "device": "auto", "enable_mkldnn": False, "low_confidence": 0.80,
        "min_image_px": 40, "reconstruct_tables": True, "normalize_variants": True,
    },
    "pdf": {"dpi": 200, "min_text_chars": 10, "ocr_embedded_images": True, "min_image_ratio": 0.15},
    "office": {"ocr_embedded_images": True, "include_hidden_sheets": True, "include_notes": True},
}


def load_config(path: Path | None) -> dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    if path and path.exists():
        user = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key, val in user.items():
            if isinstance(val, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(val)
            else:
                cfg[key] = val
    return cfg


class SkipFile(Exception):
    """対象外のファイル（パスワード付きなど）。エラーではなくスキップとして記録する。"""


@dataclass
class Result:
    markdown: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Context:
    config: dict[str, Any]
    ocr: Any  # doc2md.ocr.OcrEngine

    def ocr_image_block(self, image, label: str, meta: dict[str, Any]) -> str:
        """画像をOCRし、Markdownブロックを返す。統計は meta['ocr'] に積む。"""
        res = self.ocr.read(image)
        stats = meta.setdefault("ocr", {"images": 0, "lines": 0, "low_confidence_lines": 0, "seconds": 0.0})
        if res is None:
            return ""
        stats["images"] += 1
        stats["lines"] += res.n_lines
        stats["low_confidence_lines"] += res.n_low
        stats["seconds"] = round(stats["seconds"] + res.seconds, 2)
        if not res.markdown.strip():
            return ""
        return f"**[{label}のOCR結果]**\n\n{res.markdown}"
