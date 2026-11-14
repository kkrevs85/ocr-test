"""ファイル種別の振り分けと、出力フォルダへの書き出し。"""
from __future__ import annotations

import datetime as dt
import json
import time
import traceback
from pathlib import Path

from . import __version__
from .common import Context, SkipFile
from .extractors import docx, image, msg, pdf, pptx, text, xlsx
from .ocr import OcrEngine

EXTRACTORS = {
    ".pdf": pdf.extract,
    ".docx": docx.extract, ".pptx": pptx.extract, ".xlsx": xlsx.extract, ".xlsm": xlsx.extract,
    ".msg": msg.extract,
    ".csv": text.extract, ".tsv": text.extract, ".txt": text.extract,
    ".jpg": image.extract, ".jpeg": image.extract, ".png": image.extract,
}
LEGACY = {".xls": "旧形式（.xls）は対象外です", ".doc": "旧形式（.doc）は対象外です", ".ppt": "旧形式（.ppt）は対象外です"}


def collect(paths: list[Path], exclude: Path) -> list[tuple[Path, Path]]:
    """(ファイル, 出力時の相対パス) の一覧を返す。隠しファイルと出力フォルダは除く。"""
    found: list[tuple[Path, Path]] = []
    for p in paths:
        if p.is_file():
            found.append((p, Path(p.name)))
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if not f.is_file() or any(part.startswith((".", "~$")) for part in f.relative_to(p).parts):
                    continue
                if exclude in f.resolve().parents:
                    continue
                found.append((f, f.relative_to(p)))
    return found


def run(paths: list[Path], config: dict, output_root: Path, log=print) -> Path:
    started = dt.datetime.now()
    out_dir = output_root / started.strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=False)
    ctx = Context(config=config, ocr=OcrEngine(config["ocr"]))
    files = collect(paths, output_root.resolve())
    summary = {"tool": f"doc2md {__version__}", "started_at": started.isoformat(timespec="seconds"),
               "output_dir": str(out_dir), "files": []}
    for src, rel in files:
        ext = src.suffix.lower()
        entry = {"source": str(src), "status": "ok"}
        t = time.time()
        try:
            if ext in LEGACY:
                raise SkipFile(LEGACY[ext])
            if ext not in EXTRACTORS:
                raise SkipFile(f"未対応の拡張子です（{ext or 'なし'}）")
            result = EXTRACTORS[ext](src, ctx)
            target = out_dir / rel.parent / (rel.name + ".md")
            target.parent.mkdir(parents=True, exist_ok=True)
            front = "\n".join([
                "---", f"source: {json.dumps(src.name, ensure_ascii=False)}",
                f"type: {result.meta.get('type', ext.lstrip('.'))}",
                f"processed_at: {started.isoformat(timespec='seconds')}", "---", "",
            ])
            target.write_text(f"{front}\n# {src.name}\n\n{result.markdown.strip()}\n", encoding="utf-8")
            entry.update(output=str(target.relative_to(out_dir)), chars=len(result.markdown), meta=result.meta)
        except SkipFile as e:
            entry.update(status="skipped", reason=str(e))
        except Exception as e:  # 1ファイルの失敗でバッチ全体を止めない
            entry.update(status="error", reason=f"{type(e).__name__}: {e}", traceback=traceback.format_exc())
        entry["seconds"] = round(time.time() - t, 2)
        summary["files"].append(entry)
        log(f"[{entry['status']:7}] {entry['seconds']:7.2f}s  {rel}" + (f"  ({entry['reason']})" if "reason" in entry else ""))
    summary["ocr_init_seconds"] = ctx.ocr.init_seconds
    summary["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
    summary["counts"] = {s: sum(1 for f in summary["files"] if f["status"] == s) for s in ("ok", "skipped", "error")}
    (out_dir / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_dir
