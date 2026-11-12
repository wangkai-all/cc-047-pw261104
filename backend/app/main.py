"""FastAPI application: workspace-scoped CSV import demo.

Every data route depends on `require_workspace`, so no resource can be read,
mutated or downloaded without an explicit X-Workspace-Id that the demo
account is actually allowed to use. All SQL lookups additionally filter by
workspace_id, so an id from another workspace yields 404, not 403: the
resource simply does not exist in this workspace.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import config, db
from .deps import require_workspace
from .models import (
    CreateImportResponse,
    PreviewResponse,
    RecordListResponse,
    RecordOut,
    TaskListResponse,
    TaskOut,
    Workspace,
)
from .services import importer
from .services.csv_utils import (
    MAX_FILE_BYTES,
    iter_csv_rows,
    preview_csv,
    save_upload,
    sha256_bytes,
    suggest_mapping,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.ensure_dirs()
    db.init_db()
    yield


app = FastAPI(title="多工作区 CSV 导入演示", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------

@app.get("/api/workspaces", response_model=list[Workspace])
def list_workspaces() -> list[Workspace]:
    return [Workspace(**w) for w in config.WORKSPACES.values()]


# ---------------------------------------------------------------------------
# Preview (no persistence; still workspace-scoped by header convention)
# ---------------------------------------------------------------------------

@app.post("/api/imports/preview", response_model=PreviewResponse)
async def preview_upload(
    file: UploadFile = File(...),
    workspace_id: str = Depends(require_workspace),
) -> PreviewResponse:
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 5MB 限制")
    try:
        headers, rows = preview_csv(data)
    except Exception as exc:  # malformed CSV
        raise HTTPException(status_code=400, detail=f"CSV 解析失败: {exc}") from exc
    if not headers:
        raise HTTPException(status_code=400, detail="CSV 缺少表头")
    return PreviewResponse(
        filename=file.filename or "upload.csv",
        headers=headers,
        rows=rows,
        suggested_mapping=suggest_mapping(headers),
    )


# ---------------------------------------------------------------------------
# Import tasks
# ---------------------------------------------------------------------------

def _task_out(row) -> TaskOut:
    return TaskOut(
        id=row["id"],
        workspace_id=row["workspace_id"],
        request_id=row["request_id"],
        filename=row["filename"],
        status=row["status"],
        mapping=json.loads(row["mapping_json"]),
        file_hash=row["file_hash"],
        total_rows=row["total_rows"],
        processed_rows=row["processed_rows"],
        success_rows=row["success_rows"],
        failed_rows=row["failed_rows"],
        has_error_file=bool(row["error_file_path"]),
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@app.post("/api/imports", response_model=CreateImportResponse)
async def create_import(
    response: Response,
    request_id: str = Form(...),
    mapping: str = Form(...),
    file: UploadFile = File(...),
    workspace_id: str = Depends(require_workspace),
) -> CreateImportResponse:
    request_id = request_id.strip()
    if not request_id:
        raise HTTPException(status_code=400, detail="request_id 不能为空")
    try:
        mapping_dict = json.loads(mapping)
        if not isinstance(mapping_dict, dict) or not mapping_dict:
            raise ValueError
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="mapping 必须是非空 JSON 对象") from exc

    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 5MB 限制")
    try:
        headers, _rows = preview_csv(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"CSV 解析失败: {exc}") from exc

    # Validate the mapping against this exact file's headers before persisting.
    unknown_sources = [s for s in mapping_dict if s not in headers]
    if unknown_sources:
        raise HTTPException(
            status_code=400,
            detail=f"映射中的列在 CSV 表头中不存在: {', '.join(unknown_sources)}",
        )
    try:
        importer._validate_mapping(mapping_dict)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_hash = sha256_bytes(data)
    # Each upload attempt gets a unique physical path (uuid prefix), so an
    # idempotent retry that is discarded never deletes the original task's
    # file. The workspace segment still keeps the two tenants' files apart.
    import uuid

    safe_name = Path(file.filename or "upload.csv").name
    dest = (
        config.STORAGE_DIR
        / workspace_id
        / "uploads"
        / f"{request_id}__{uuid.uuid4().hex[:8]}__{safe_name}"
    )
    save_upload(data, dest)
    total_rows = sum(1 for _ in iter_csv_rows(str(dest)))

    try:
        result = importer.create_or_reuse(
            workspace_id=workspace_id,
            request_id=request_id,
            filename=file.filename or "upload.csv",
            file_hash=file_hash,
            mapping=mapping_dict,
            storage_path=str(dest),
            total_rows=total_rows,
        )
    except importer.FileConflictError as conflict:
        # The conflicting fresh upload belongs to no task; remove it.
        Path(dest).unlink(missing_ok=True)
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"请求编号 {request_id} 已存在但{conflict}",
                "existing_task_id": conflict.existing["id"],
                "same_hash": conflict.same_hash,
                "same_mapping": conflict.same_mapping,
            },
        ) from conflict

    if not result.reused:
        importer.start_worker(result.task["id"])
        response.status_code = 201
    else:
        response.status_code = 200
    return CreateImportResponse(reused=result.reused, task=_task_out(result.task))


@app.get("/api/imports", response_model=TaskListResponse)
def list_imports(workspace_id: str = Depends(require_workspace)) -> TaskListResponse:
    rows = db.query_all(
        "SELECT * FROM import_tasks WHERE workspace_id = ? ORDER BY id DESC",
        (workspace_id,),
    )
    return TaskListResponse(items=[_task_out(r) for r in rows])


@app.get("/api/imports/{task_id}", response_model=TaskOut)
def get_import(task_id: int, workspace_id: str = Depends(require_workspace)) -> TaskOut:
    row = importer.find_task(workspace_id, task_id)
    if row is None:
        # Same response whether the id belongs to another workspace or does
        # not exist at all: no cross-workspace enumeration oracle.
        raise HTTPException(status_code=404, detail=f"工作区 {workspace_id} 中找不到任务 {task_id}")
    return _task_out(row)


@app.post("/api/imports/{task_id}/cancel")
def cancel_import(task_id: int, workspace_id: str = Depends(require_workspace)) -> TaskOut:
    row = importer.find_task(workspace_id, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"工作区 {workspace_id} 中找不到任务 {task_id}")
    if row["status"] in ("pending", "running"):
        importer.request_cancel(task_id)
    row = importer.find_task(workspace_id, task_id)
    return _task_out(row)


@app.delete("/api/imports/{task_id}")
def delete_import(task_id: int, workspace_id: str = Depends(require_workspace)) -> dict:
    row = importer.find_task(workspace_id, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"工作区 {workspace_id} 中找不到任务 {task_id}")
    if row["status"] in ("pending", "running"):
        raise HTTPException(status_code=409, detail="任务仍在执行，请先取消再清理")
    importer.cleanup_task_files(row)
    db.execute("DELETE FROM records WHERE task_id = ? AND workspace_id = ?",
               (task_id, workspace_id))
    db.execute("DELETE FROM import_tasks WHERE id = ? AND workspace_id = ?",
               (task_id, workspace_id))
    return {"deleted": task_id, "workspace_id": workspace_id}


@app.get("/api/imports/{task_id}/errors")
def download_errors(task_id: int, workspace_id: str = Depends(require_workspace)):
    row = importer.find_task(workspace_id, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"工作区 {workspace_id} 中找不到任务 {task_id}")
    if not row["error_file_path"]:
        raise HTTPException(status_code=404, detail="该任务没有错误文件")
    path = Path(row["error_file_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="错误文件已被清理")
    return FileResponse(
        path,
        media_type="text/csv",
        filename=f"{workspace_id}_task{task_id}_errors.csv",
    )


# ---------------------------------------------------------------------------
# Imported records & raw file download
# ---------------------------------------------------------------------------

@app.get("/api/records", response_model=RecordListResponse)
def list_records(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    business_key: str | None = Query(default=None),
    workspace_id: str = Depends(require_workspace),
) -> RecordListResponse:
    where = "WHERE workspace_id = ?"
    params: list = [workspace_id]
    if business_key:
        where += " AND business_key = ?"
        params.append(business_key)
    total = db.query_one(
        f"SELECT COUNT(*) AS c FROM records {where}", tuple(params)
    )["c"]
    params.extend([limit, offset])
    rows = db.query_all(
        f"""SELECT * FROM records {where}
            ORDER BY id DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    items = [
        RecordOut(
            business_key=r["business_key"],
            workspace_id=r["workspace_id"],
            task_id=r["task_id"],
            row_number=r["row_number"],
            payload=json.loads(r["payload_json"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return RecordListResponse(items=items, total=total, limit=limit, offset=offset)


@app.get("/api/imports/{task_id}/download")
def download_source(task_id: int, workspace_id: str = Depends(require_workspace)):
    row = importer.find_task(workspace_id, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"工作区 {workspace_id} 中找不到任务 {task_id}")
    path = Path(row["storage_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="原始文件已被清理")
    return FileResponse(
        path,
        media_type="text/csv",
        filename=f"{workspace_id}_{row['filename']}",
    )
