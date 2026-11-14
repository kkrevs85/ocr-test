"""コマンドライン入口: uv run doc2md [入力...]"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .common import load_config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="doc2md", description="文書を構造を保ったMarkdownに変換します。")
    ap.add_argument("inputs", nargs="*", type=Path, help="ファイルまたはフォルダ（省略時は ./input）")
    ap.add_argument("--config", type=Path, default=Path("config.yaml"), help="設定ファイル（既定: ./config.yaml）")
    ap.add_argument("--output-root", type=Path, help="出力の親フォルダ（既定: 設定の output_root）")
    ap.add_argument("--no-ocr", action="store_true", help="OCRを使わず、直接パースできるものだけ処理する")
    args = ap.parse_args(argv)

    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    config = load_config(args.config)
    if args.no_ocr:
        config["ocr"]["enabled"] = False
    inputs = args.inputs or [Path("input")]
    missing = [p for p in inputs if not p.exists()]
    if missing:
        print("入力が見つかりません: " + ", ".join(str(p) for p in missing), file=sys.stderr)
        return 2
    from .pipeline import run
    out_dir = run(inputs, config, args.output_root or Path(config["output_root"]))
    print(f"出力先: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
