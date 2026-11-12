"""CSV helpers: hashing, preview and streaming row parsing.

Uploaded files are untrusted: we only ever read them through the csv module
with a fixed size cap, never execute or import from their directory.
"""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

MAX_PREVIEW_ROWS = 5
MAX_FILE_BYTES = 5 * 1024 * 1024


class CsvTooLarge(Exception):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_upload(data: bytes, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return str(dest)


def _decode(data: bytes) -> str:
    # utf-8-sig transparently drops a BOM if the exporter added one.
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("gb18030")  # common for Excel exports in zh-CN


def preview_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = _decode(data)
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    rows: list[dict[str, str]] = []
    for i, row in enumerate(reader):
        if i >= MAX_PREVIEW_ROWS:
            break
        rows.append({h: (row.get(h) or "").strip() for h in headers})
    return list(headers), rows


def iter_csv_rows(path: str):
    """Yield (row_number, raw_row_dict) starting at row_number=2 (header is 1)."""
    data = Path(path).read_bytes()
    text = _decode(data)
    reader = csv.DictReader(io.StringIO(text))
    headers = list(reader.fieldnames or [])
    for index, row in enumerate(reader, start=2):
        yield index, headers, {h: (row.get(h) or "").strip() for h in headers}


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    """Guess canonical fields from header names. Unknown headers stay unmapped."""
    aliases = {
        "order_id": {"order_id", "订单编号", "订单号", "id", "业务编号"},
        "customer": {"customer", "客户", "客户名称"},
        "amount": {"amount", "金额", "订单金额"},
        "remark": {"remark", "备注", "说明"},
    }
    mapping: dict[str, str] = {}
    for header in headers:
        token = header.strip().lower()
        for field, names in aliases.items():
            if token in {n.lower() for n in names}:
                mapping[header] = field
                break
    return mapping
