"""Outlook の .msg。ヘッダと本文のみ（添付は対象外、ファイル名だけ記録）。"""
from __future__ import annotations

from pathlib import Path

from markdownify import markdownify
from oxmsg import Message

from ..common import Context, Result
from ..tables import pipe_table


def extract(path: Path, ctx: Context) -> Result:
    msg = Message.load(str(path))
    headers = {}
    try:
        headers = {k.lower(): v for k, v in msg.message_headers.items()}
    except Exception:
        pass
    recipients = []
    for r in msg.recipients:
        try:
            name, addr = r.name, r.email_address
            recipients.append(f"{name} <{addr}>" if addr and addr != name else name)
        except Exception:
            continue
    sent = msg.sent_date.isoformat() if msg.sent_date else ""
    attachments = []
    for a in msg.attachments:
        try:
            attachments.append(a.file_name or "")
        except Exception:
            attachments.append("")
    rows = [["項目", "内容"], ["件名", msg.subject or ""], ["差出人", msg.sender or headers.get("from", "")]]
    if headers.get("to") or headers.get("cc"):
        rows.append(["宛先", headers.get("to", "")])
        if headers.get("cc"):
            rows.append(["CC", headers["cc"]])
    else:
        rows.append(["宛先", "; ".join(recipients)])
    rows.append(["送信日時", sent])
    if attachments:
        rows.append(["添付（未処理）", ", ".join(a for a in attachments if a)])

    body = (msg.body or "").replace("\r\n", "\n").strip()
    html = msg.html_body
    body_source = "plain"
    if html and ("<table" in html.lower() or not body):
        body = markdownify(html, heading_style="ATX", strip=["img", "style", "script"]).strip()
        body_source = "html"
    meta = {"type": "msg", "subject": msg.subject, "sender": msg.sender, "sent": sent,
            "recipients": recipients, "attachments_skipped": attachments, "body_source": body_source}
    return Result(pipe_table(rows) + "\n\n## 本文\n\n" + body, meta)
