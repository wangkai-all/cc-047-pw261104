"""Pydantic response / request schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Workspace(BaseModel):
    id: str
    name: str


class PreviewResponse(BaseModel):
    filename: str
    headers: list[str]
    rows: list[dict[str, str]]
    suggested_mapping: dict[str, str]


class TaskOut(BaseModel):
    id: int
    workspace_id: str
    request_id: str
    filename: str
    status: str
    mapping: dict[str, str]
    file_hash: str
    total_rows: int
    processed_rows: int
    success_rows: int
    failed_rows: int
    has_error_file: bool
    error_message: str | None
    created_at: str
    updated_at: str


class TaskListResponse(BaseModel):
    items: list[TaskOut]


class RecordOut(BaseModel):
    business_key: str
    workspace_id: str
    task_id: int
    row_number: int
    payload: dict[str, Any]
    created_at: str


class RecordListResponse(BaseModel):
    items: list[RecordOut]
    total: int
    limit: int
    offset: int


class CreateImportResponse(BaseModel):
    reused: bool
    task: TaskOut
