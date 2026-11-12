"""Import task lifecycle: creation with idempotency, background execution,
cancellation and cleanup.

Key isolation rules implemented here:
- A task is bound to (workspace_id, request_id) at creation; the background
  worker re-reads that binding from the DB and never consults any
  client-side "current workspace".
- Same request_id in two different workspaces are different rows thanks to
  the UNIQUE(workspace_id, request_id) constraint.
- Reusing a request_id is allowed only when file hash and field mapping are
  identical; any other reuse returns 409 conflict.
- Cancellation and cleanup touch only this task's own storage files.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .. import config, db
from .csv_utils import iter_csv_rows

CANONICAL_FIELDS = ("order_id", "customer", "amount", "remark")
REQUIRED_FIELDS = ("order_id", "customer", "amount")

# In-process cancellation flags. Workers are threads inside this one process,
# so an in-memory event is sufficient and stays consistent with task rows.
_cancel_events: dict[int, threading.Event] = {}
_locks_guard = threading.Lock()


@dataclass
class CreateResult:
    task: db.sqlite3.Row
    reused: bool


def _cancel_event(task_id: int) -> threading.Event:
    with _locks_guard:
        event = _cancel_events.get(task_id)
        if event is None:
            event = threading.Event()
            _cancel_events[task_id] = event
        return event


def request_cancel(task_id: int) -> None:
    _cancel_event(task_id).set()


def clear_cancel_event(task_id: int) -> None:
    with _locks_guard:
        _cancel_events.pop(task_id, None)


def find_task(workspace_id: str, task_id: int):
    """Workspace-scoped lookup: a task from another workspace is 'not found'."""
    return db.query_one(
        "SELECT * FROM import_tasks WHERE id = ? AND workspace_id = ?",
        (task_id, workspace_id),
    )


def create_or_reuse(
    *,
    workspace_id: str,
    request_id: str,
    filename: str,
    file_hash: str,
    mapping: dict[str, str],
    storage_path: str,
    total_rows: int,
) -> CreateResult:
    """Idempotent create. Caller holds the uploaded file at storage_path."""
    mapping_json = json.dumps(mapping, ensure_ascii=False, sort_keys=True)
    existing = db.query_one(
        "SELECT * FROM import_tasks WHERE workspace_id = ? AND request_id = ?",
        (workspace_id, request_id),
    )
    if existing is not None:
        same_hash = existing["file_hash"] == file_hash
        same_mapping = existing["mapping_json"] == mapping_json
        if same_hash and same_mapping:
            # Identical request: the stored task is the answer; the freshly
            # uploaded duplicate file is removed so only one copy remains.
            Path(storage_path).unlink(missing_ok=True)
            return CreateResult(task=existing, reused=True)
        raise FileConflictError(existing, same_hash, same_mapping)

    cur = db.execute(
        """
        INSERT INTO import_tasks
            (workspace_id, request_id, filename, status, mapping_json,
             file_hash, storage_path, total_rows)
        VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
        """,
        (workspace_id, request_id, filename, mapping_json,
         file_hash, storage_path, total_rows),
    )
    task = db.query_one("SELECT * FROM import_tasks WHERE id = ?", (cur.lastrowid,))
    return CreateResult(task=task, reused=False)


class FileConflictError(Exception):
    def __init__(self, existing, same_hash: bool, same_mapping: bool):
        self.existing = existing
        self.same_hash = same_hash
        self.same_mapping = same_mapping
        reasons = []
        if not same_hash:
            reasons.append("文件内容不同")
        if not same_mapping:
            reasons.append("字段映射不同")
        super().__init__("；".join(reasons))


def start_worker(task_id: int) -> None:
    thread = threading.Thread(
        target=_run_worker, args=(task_id,), name=f"import-{task_id}", daemon=True
    )
    thread.start()


def _set_status(task_id: int, status: str, error_message: str | None = None) -> None:
    db.execute(
        "UPDATE import_tasks SET status = ?, error_message = ?, updated_at = datetime('now') WHERE id = ?",
        (status, error_message, task_id),
    )


def _validate_mapping(mapping: dict[str, str]) -> None:
    targets = set(mapping.values())
    missing = [f for f in REQUIRED_FIELDS if f not in targets]
    if missing:
        raise ValueError(f"映射缺少必填字段: {', '.join(missing)}")
    for target in targets:
        if target not in CANONICAL_FIELDS:
            raise ValueError(f"未知的目标字段: {target}")


def _run_worker(task_id: int) -> None:
    # Each thread opens its own SQLite connection via the thread-local in db.
    event = _cancel_event(task_id)
    try:
        task = db.query_one("SELECT * FROM import_tasks WHERE id = ?", (task_id,))
        if task is None:
            return
        mapping = json.loads(task["mapping_json"])
        _validate_mapping(mapping)
        _set_status(task_id, "running")

        error_rows: list[dict[str, str | int]] = []
        processed = success = failed = 0
        cancel_happened = False

        for row_number, _headers, raw in iter_csv_rows(task["storage_path"]):
            if event.is_set():
                cancel_happened = True
                break

            processed += 1
            mapped = {target: raw.get(src, "").strip()
                      for src, target in mapping.items()}
            business_key = mapped.get("order_id", "")
            errors: list[str] = []
            if not business_key:
                errors.append("订单编号为空")
            if not mapped.get("customer"):
                errors.append("客户为空")
            amount_raw = mapped.get("amount", "")
            amount_value: float | None = None
            try:
                amount_value = float(amount_raw)
                if amount_value < 0:
                    errors.append("金额不能为负")
            except (TypeError, ValueError):
                errors.append(f"金额无法解析: {amount_raw!r}")

            if errors:
                failed += 1
                error_rows.append({"row_number": row_number,
                                   "reason": "；".join(errors),
                                   **raw})
            else:
                payload = {
                    "order_id": business_key,
                    "customer": mapped["customer"],
                    "amount": amount_value,
                    "remark": mapped.get("remark", ""),
                }
                try:
                    db.execute(
                        """INSERT INTO records (workspace_id, task_id, business_key,
                                               payload_json, row_number)
                           VALUES (?, ?, ?, ?, ?)""",
                        (task["workspace_id"], task_id, business_key,
                         json.dumps(payload, ensure_ascii=False), row_number),
                    )
                    success += 1
                except db.sqlite3.IntegrityError:
                    # Duplicate business key *within the same workspace*.
                    failed += 1
                    error_rows.append({"row_number": row_number,
                                       "reason": f"业务编号 {business_key} 在本工作区已存在",
                                       **raw})

            # Persist progress after every row so the UI and a mid-run
            # workspace switch always observe a consistent state.
            db.execute(
                """UPDATE import_tasks
                   SET processed_rows = ?, success_rows = ?, failed_rows = ?,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (processed, success, failed, task_id),
            )
            if config.ROW_DELAY_SECONDS > 0:
                # Interruptible sleep: cancellation reacts within ~0.05s.
                if event.wait(config.ROW_DELAY_SECONDS):
                    cancel_happened = True
                    break

        error_path = None
        if error_rows:
            error_path = _write_error_file(task, error_rows)
            db.execute(
                "UPDATE import_tasks SET error_file_path = ? WHERE id = ?",
                (error_path, task_id),
            )

        final_status = "cancelled" if cancel_happened else (
            "failed" if failed and not success else "completed"
        )
        if cancel_happened:
            msg = f"已取消：已处理 {processed} 行，成功 {success}，失败 {failed}"
        elif final_status == "failed":
            msg = f"全部 {failed} 行校验失败"
        else:
            msg = None
        db.execute(
            """UPDATE import_tasks SET status = ?, error_message = ?,
                   processed_rows = ?, success_rows = ?, failed_rows = ?,
                   updated_at = datetime('now') WHERE id = ?""",
            (final_status, msg, processed, success, failed, task_id),
        )
    except Exception as exc:  # noqa: BLE001 - worker must never die silently
        _set_status(task_id, "failed", f"后台执行异常: {exc}")
    finally:
        clear_cancel_event(task_id)


def _write_error_file(task, error_rows: list[dict]) -> str:
    import csv as _csv

    ws_dir = config.STORAGE_DIR / task["workspace_id"] / "errors"
    ws_dir.mkdir(parents=True, exist_ok=True)
    path = ws_dir / f"task_{task['id']}_errors.csv"
    fieldnames = ["row_number", "reason"]
    extra = sorted({k for row in error_rows for k in row if k not in fieldnames})
    fieldnames.extend(extra)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in error_rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return str(path)


def cleanup_task_files(task) -> None:
    """Delete only files owned by this task; DB rows are removed by the caller."""
    for attr in ("storage_path", "error_file_path"):
        value = task[attr]
        if value:
            Path(value).unlink(missing_ok=True)
