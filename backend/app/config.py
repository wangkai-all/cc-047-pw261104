"""Runtime configuration. Everything is overridable via environment variables."""
from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


# Root of all runtime data (sqlite db + uploaded files). Kept outside the
# source tree so untrusted uploads never sit next to importable code.
DATA_DIR = Path(_env("APP_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))
STORAGE_DIR = DATA_DIR / "storage"
DB_PATH = DATA_DIR / "app.db"

# Delay applied per processed CSV row so the UI can show progress and the
# demo can switch workspaces while an import is still running. Set to 0 in tests.
ROW_DELAY_SECONDS = float(_env("IMPORT_ROW_DELAY", "0.4"))

# The single local demo account. It may access exactly these two workspaces.
# No real auth system: the client states which workspace it acts in on every
# request, and the server validates membership here.
DEMO_ACCOUNT_ID = "demo-account"
WORKSPACES: dict[str, dict[str, str]] = {
    "ws-alpha": {"id": "ws-alpha", "name": "Alpha 工作区"},
    "ws-beta": {"id": "ws-beta", "name": "Beta 工作区"},
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
