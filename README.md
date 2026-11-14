# doc2md — 文書テキスト化（OCR）パイプライン

PDF（スキャン含む）、Office文書、メール、csv / txt、画像を、表などの構造を保ったMarkdownに変換するバッチツールです。
OCRが不要なファイルは構造を直接読み取り、スキャンPDF・画像・Office文書内の埋め込み画像だけをPaddleOCRで読み取ります。
処理はすべてローカルで完結し、文書を外部に送信しません（初回のみOCRモデルをダウンロードします）。

## セットアップ

[uv](https://docs.astral.sh/uv/) を使います。このフォルダで次を実行すると、`.venv` に仮想環境が作られます。

```bash
uv sync
```

## 使い方

```bash
# input フォルダ内のファイルをすべて処理（サブフォルダも対象）
uv run doc2md

# ファイルやフォルダを指定
uv run doc2md path/to/file.pdf path/to/folder

# OCRを使わず、直接パースできるものだけ処理（高速。動作確認向け）
uv run doc2md --no-ocr
```

結果は `output/YYYYMMDD_HHMMSS/`（処理開始の日付・時分秒）に保存されます。

| ファイル | 内容 |
| --- | --- |
| `<元のファイル名>.md` | テキスト化結果。先頭に元ファイル名・種別・処理日時を記載 |
| `_summary.json` | ファイルごとの状態（ok / skipped / error）、処理時間、ページ数、OCRの行数と低信頼行数など |

## 対応形式と処理方法

| 形式 | 処理 |
| --- | --- |
| pdf（テキスト層あり） | 文字と罫線から本文と表を直接抽出。ページ内の大きな画像はOCR |
| pdf（スキャン） | ページを画像化してOCR。行の座標から表を復元 |
| jpeg / png | OCR。行の座標から表を復元 |
| docx | 見出し・段落・箇条書き・表を文書順に抽出。埋め込み画像はOCR |
| pptx | スライドごとにタイトル・本文・表・グラフ・ノートを抽出。画像はOCR |
| xlsx / xlsm | シートごとに使用範囲を表として抽出。結合セル、表示形式（桁区切り・％・△・日付）、非表示シート、グラフに対応。画像はOCRし、貼付位置のセルを併記 |
| msg | 件名・差出人・宛先・送信日時と本文。添付はファイル名のみ記録（中身は対象外） |
| csv / tsv / txt | 文字コードを自動判定（UTF-8、Shift_JIS など）。csv / tsv は表にする |

結合セルのない表はMarkdownのパイプ表、結合セルのある表はHTML表で出力します。
旧形式（.xls / .doc / .ppt）と、開くのにパスワードが必要なファイルは対象外で、`_summary.json` に skipped として記録します。

## 設定（config.yaml）

主な項目です。詳細はファイル内のコメントを参照してください。

| 項目 | 既定値 | 説明 |
| --- | --- | --- |
| `ocr.detection_model` / `ocr.recognition_model` | 空（高精度モデル） | 速度優先なら `PP-OCRv5_mobile_det` / `PP-OCRv5_mobile_rec` |
| `ocr.device` | `auto` | `cpu` / `gpu:0` を明示可能 |
| `ocr.low_confidence` | `0.80` | これ未満の行を低信頼として数える |
| `ocr.normalize_variants` | `true` | 中国語字体で出た漢字（產→産 など）を日本の字体に直す |
| `pdf.dpi` | `200` | スキャンページを画像化する解像度 |

## Linux・GPUで動かす場合

`uv sync` で入る `paddlepaddle` はCPU版です。GPUを使う場合は、CUDAのバージョンに合った `paddlepaddle-gpu` をPaddlePaddle公式の手順で入れ替えてください。`ocr.device: auto` のままでGPUを自動的に使います。

## 既知の制限

- 手書き文字の精度は未検証です。低信頼の行数を `_summary.json` に出力するので、しきい値での切り分けに使えます。
- OCRでは注記記号「※」が抜けることがあります。
- OCRで復元した表は、列見出しの文字間が空いている場合（「科　目」など）に見出しが複数列に分かれることがあります。
- スキャンした表の結合セルは復元しません（直接パースできるOffice文書では復元します）。
- xlsxのグラフは、ファイルに保存された値を読みます。値が保存されていない場合は参照範囲のみ出力します。
- docxのテキストボックス、ヘッダー・フッターは抽出しません。
- 金額の検算（合計と内訳の一致）と、LLMによる低信頼ページの再読取りは未実装です。

## 利用ライブラリのライセンス

| ライブラリ | 用途 | ライセンス |
| --- | --- | --- |
| PaddleOCR / PaddlePaddle | OCR | Apache-2.0 |
| pdfplumber | PDFの文字・表の抽出 | MIT |
| pypdfium2 | PDFの画像化 | Apache-2.0 / BSD-3-Clause |
| python-docx / python-pptx / openpyxl | Office文書 | MIT |
| python-oxmsg | msg | MIT |
| markdownify | メールのHTML本文 | MIT |
| charset-normalizer | 文字コード判定 | MIT |
| Pillow | 画像 | MIT-CMU |
| PyYAML | 設定 | MIT |

社内配布の前に、`uv pip list` の全依存について各リポジトリのLICENSEを確認してください。
