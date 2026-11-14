"""csv / tsv / txt。文字コードを判定して読む。"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from charset_normalizer import from_bytes

from ..common import Context, Result
from ..tables import pipe_table


def decode(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp932"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    best = from_bytes(data).best()
    if best is not None:
        return str(best), best.encoding
    return data.decode("utf-8", errors="replace"), "utf-8(replace)"


def extract(path: Path, ctx: Context) -> Result:
    text, enc = decode(path.read_bytes())
    meta: dict = {"type": path.suffix.lower().lstrip("."), "encoding": enc}
    if path.suffix.lower() in (".csv", ".tsv"):
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        if path.suffix.lower() == ".csv":
            try:
                delimiter = csv.Sniffer().sniff(text[:5000], delimiters=",\t;").delimiter
            except csv.Error:
                pass
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in r)]
        meta["rows"] = len(rows)
        return Result(pipe_table(rows), meta)
    return Result(text.replace("\r\n", "\n").strip(), meta)
