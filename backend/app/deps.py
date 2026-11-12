"""Shared FastAPI dependencies: per-request workspace scoping.

Every data-access request must state the workspace it acts in via the
X-Workspace-Id header. The demo account may only use the two known
workspaces; anything else is rejected before any resource is touched.
"""
from __future__ import annotations

from fastapi import Header, HTTPException

from .config import WORKSPACES


def require_workspace(x_workspace_id: str | None = Header(default=None)) -> str:
    if not x_workspace_id:
        raise HTTPException(status_code=400, detail="缺少 X-Workspace-Id 请求头")
    if x_workspace_id not in WORKSPACES:
        raise HTTPException(status_code=403, detail=f"无权访问工作区: {x_workspace_id}")
    return x_workspace_id
