"""PaddleOCR のラッパーと、OCR結果（行の座標）からのレイアウト復元。"""
from __future__ import annotations

import re
import statistics
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .tables import pipe_table

_NUM_SPACE = re.compile(r"(?<=\d,) (?=\d)")


@dataclass
class Line:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    score: float

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class OcrResult:
    markdown: str
    n_lines: int
    n_low: int
    mean_score: float
    seconds: float


# PaddleOCR の日本語認識は、一部の漢字を中国語の字体（簡体字・繁体字）で出力する癖がある。
# 日本語の文書では通常使わない字体だけを、対応する日本の字体に直す。
VARIANT_MAP = str.maketrans({
    "產": "産", "产": "産", "卻": "却", "剩": "剰", "壳": "売", "单": "単", "额": "額", "雜": "雑",
    "资": "資", "损": "損", "计": "計", "费": "費", "债": "債", "报": "報", "负": "負", "证": "証",
    "證": "証", "备": "備", "设": "設", "营": "営", "營": "営", "业": "業", "长": "長", "贷": "貸",
    "预": "預", "现": "現", "库": "庫", "总": "総", "總": "総", "减": "減", "偿": "償", "价": "価",
    "價": "価", "权": "権", "權": "権", "银": "銀", "稅": "税", "续": "続", "变": "変", "动": "動",
})
_KATA = re.compile(r"[ァ-ヴー]")
_HIRA_KATA = {"へ": "ヘ", "べ": "ベ", "ぺ": "ペ"}


def _fix_he(text: str) -> str:
    """字形が同じ「へ／ヘ」「べ／ベ」「ぺ／ペ」を、隣がカタカナならカタカナに寄せる。"""
    chars = list(text)
    for i, ch in enumerate(chars):
        if ch in _HIRA_KATA:
            prev = chars[i - 1] if i > 0 else ""
            nxt = chars[i + 1] if i + 1 < len(chars) else ""
            if _KATA.fullmatch(prev or " ") or _KATA.fullmatch(nxt or " "):
                chars[i] = _HIRA_KATA[ch]
    return "".join(chars)


def clean_text(text: str, normalize_variants: bool = True) -> str:
    """OCR特有の崩れを直す（桁区切りの後ろの空白、中国語字体、へ／ヘの取り違え）。"""
    text = _NUM_SPACE.sub("", text).strip()
    if normalize_variants:
        text = _fix_he(text.translate(VARIANT_MAP))
    return text


def group_rows(lines: list[Line]) -> list[list[Line]]:
    """縦位置が近い行を同じ行としてまとめ、左から順に並べる。"""
    if not lines:
        return []
    med_h = statistics.median(l.h for l in lines) or 1.0
    rows: list[list[Line]] = []
    for line in sorted(lines, key=lambda l: l.yc):
        if rows and abs(line.yc - statistics.mean(l.yc for l in rows[-1])) < med_h * 0.6:
            rows[-1].append(line)
        else:
            rows.append([line])
    return [sorted(r, key=lambda l: l.x0) for r in rows]


def _table_runs(rows: list[list[Line]], max_single_gap: int = 3) -> list[tuple[int, int]]:
    """複数セグメントの行が続く範囲を表の候補とする。途中の1セグメント行は少数なら含める。"""
    multi = [i for i, r in enumerate(rows) if len(r) >= 2]
    runs: list[tuple[int, int]] = []
    for i in multi:
        if runs and i - runs[-1][1] <= max_single_gap + 1:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    # 2行未満の「表」は表にしない
    return [(a, b) for a, b in runs if sum(1 for i in range(a, b + 1) if len(rows[i]) >= 2) >= 2]


def _columns(rows: list[list[Line]]) -> list[tuple[float, float]]:
    """複数セグメント行の横方向の占有範囲を合成し、列の範囲を求める。"""
    spans = sorted((l.x0, l.x1) for r in rows if len(r) >= 2 for l in r)
    cols: list[list[float]] = []
    for x0, x1 in spans:
        if cols and x0 <= cols[-1][1] + 2:
            cols[-1][1] = max(cols[-1][1], x1)
        else:
            cols.append([x0, x1])
    return [(a, b) for a, b in cols]


def _col_index(cols: list[tuple[float, float]], line: Line) -> int:
    xc = (line.x0 + line.x1) / 2
    best, best_d = 0, float("inf")
    for i, (a, b) in enumerate(cols):
        d = 0.0 if a <= xc <= b else min(abs(xc - a), abs(xc - b))
        if d < best_d:
            best, best_d = i, d
    return best


def layout_markdown(lines: list[Line], reconstruct_tables: bool = True) -> str:
    """行の座標から段落と表を復元してMarkdownにする。"""
    rows = group_rows(lines)
    if not rows:
        return ""
    med_h = statistics.median(l.h for l in lines) or 1.0
    runs = _table_runs(rows) if reconstruct_tables else []
    in_run = {i: run for run in runs for i in range(run[0], run[1] + 1)}
    out: list[str] = []
    para: list[str] = []
    prev_bottom: float | None = None

    def flush() -> None:
        if para:
            out.append("\n".join(para))
            para.clear()

    i = 0
    while i < len(rows):
        if i in in_run:
            flush()
            a, b = in_run[i]
            block = rows[a:b + 1]
            cols = _columns(block)
            table = []
            for r in block:
                cells = [""] * len(cols)
                for l in r:
                    k = _col_index(cols, l)
                    cells[k] = (cells[k] + " " + l.text).strip()
                table.append(cells)
            out.append(pipe_table(table))
            prev_bottom = max(l.y1 for l in block[-1])
            i = b + 1
            continue
        row = rows[i]
        top = min(l.y0 for l in row)
        if prev_bottom is not None and top - prev_bottom > med_h * 1.2:
            flush()
        para.append(" ".join(l.text for l in row))
        prev_bottom = max(l.y1 for l in row)
        i += 1
    flush()
    return "\n\n".join(out)


class OcrEngine:
    """PaddleOCR を必要になったときに初期化する。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._engine = None
        self.init_seconds = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", True))

    def _device(self) -> str:
        dev = self.cfg.get("device", "auto")
        if dev != "auto":
            return dev
        try:
            import paddle
            if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
                return "gpu:0"
        except Exception:
            pass
        return "cpu"

    def _load(self):
        if self._engine is None:
            t = time.time()
            from paddleocr import PaddleOCR
            kwargs = dict(
                use_doc_orientation_classify=False, use_doc_unwarping=False,
                use_textline_orientation=False, device=self._device(),
                enable_mkldnn=bool(self.cfg.get("enable_mkldnn", False)),
            )
            det, rec = self.cfg.get("detection_model"), self.cfg.get("recognition_model")
            if det and rec:
                kwargs.update(text_detection_model_name=det, text_recognition_model_name=rec)
            else:
                kwargs.update(lang=self.cfg.get("lang", "japan"))
            self._engine = PaddleOCR(**kwargs)
            self.init_seconds = round(time.time() - t, 2)
        return self._engine

    def read_lines(self, image: Image.Image) -> list[Line]:
        arr = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()  # RGB -> BGR
        res = self._load().predict(arr)[0]
        lines = []
        for box, text, score in zip(res["rec_boxes"], res["rec_texts"], res["rec_scores"]):
            text = clean_text(str(text), bool(self.cfg.get("normalize_variants", True)))
            if text:
                x0, y0, x1, y1 = (float(v) for v in box)
                lines.append(Line(x0, y0, x1, y1, text, float(score)))
        return lines

    def read(self, image: Image.Image) -> OcrResult | None:
        """画像をOCRする。OCR無効、または画像が小さすぎる場合は None。"""
        if not self.enabled:
            return None
        min_px = int(self.cfg.get("min_image_px", 40))
        if image.width < min_px or image.height < min_px:
            return None
        t = time.time()
        lines = self.read_lines(image)
        low_th = float(self.cfg.get("low_confidence", 0.8))
        md = layout_markdown(lines, bool(self.cfg.get("reconstruct_tables", True)))
        return OcrResult(
            markdown=md, n_lines=len(lines), n_low=sum(1 for l in lines if l.score < low_th),
            mean_score=round(statistics.mean(l.score for l in lines), 4) if lines else 0.0,
            seconds=round(time.time() - t, 2),
        )
