"""End-to-end isolation guarantees for the two-workspace demo account."""
from __future__ import annotations

import io
import json
from pathlib import Path

from app import config


# ---------------------------------------------------------------------------
# Workspace header enforcement
# ---------------------------------------------------------------------------

def test_workspace_header_required(client):
    r = client.get("/api/imports")
    assert r.status_code == 400
    assert "X-Workspace-Id" in r.json()["detail"]


def test_unknown_workspace_rejected(client):
    r = client.get("/api/imports", headers={"X-Workspace-Id": "ws-evil"})
    assert r.status_code == 403


def test_workspaces_listing(client):
    r = client.get("/api/workspaces")
    assert r.status_code == 200
    ids = {w["id"] for w in r.json()}
    assert ids == {"ws-alpha", "ws-beta"}


# ---------------------------------------------------------------------------
# Cross-workspace invisibility: same ids/names, independent results
# ---------------------------------------------------------------------------

def test_parallel_imports_same_filename_overlapping_keys(
    client, alpha_headers, beta_headers, mapping, alpha_file, beta_file,
    uploader, wait_terminal,
):
    r1 = uploader(client, alpha_headers, "REQ-1", alpha_file, mapping)
    r2 = uploader(client, beta_headers, "REQ-1", beta_file, mapping)
    assert r1.status_code == 201 and r2.status_code == 201
    t1, t2 = r1.json()["task"], r2.json()["task"]

    a = wait_terminal(client, alpha_headers, t1["id"])
    b = wait_terminal(client, beta_headers, t2["id"])
    assert a["workspace_id"] == "ws-alpha"
    assert b["workspace_id"] == "ws-beta"
    # alpha: 3 valid rows (1001,1002,1004), 3 invalid; beta: 5 valid, 1 invalid
    assert a["success_rows"] == 3 and a["failed_rows"] == 3
    assert b["success_rows"] == 5 and b["failed_rows"] == 1

    # Lists are scoped: each workspace sees only its own task.
    la = client.get("/api/imports", headers=alpha_headers).json()["items"]
    lb = client.get("/api/imports", headers=beta_headers).json()["items"]
    assert [t["id"] for t in la] == [t1["id"]]
    assert [t["id"] for t in lb] == [t2["id"]]

    # Bringing the other workspace's batch id returns 404, never the row.
    assert client.get(f"/api/imports/{t2['id']}", headers=alpha_headers).status_code == 404
    assert client.get(f"/api/imports/{t1['id']}", headers=beta_headers).status_code == 404


def test_records_with_overlapping_business_keys_are_independent(
    client, alpha_headers, beta_headers, mapping, alpha_file, beta_file,
    uploader, wait_terminal,
):
    t1 = uploader(client, alpha_headers, "REQ-KEYS", alpha_file, mapping).json()["task"]
    t2 = uploader(client, beta_headers, "REQ-KEYS", beta_file, mapping).json()["task"]
    wait_terminal(client, alpha_headers, t1["id"])
    wait_terminal(client, beta_headers, t2["id"])

    # ORD-1001 exists in both workspaces with different payloads.
    ra = client.get("/api/records", headers=alpha_headers,
                    params={"business_key": "ORD-1001"}).json()
    rb = client.get("/api/records", headers=beta_headers,
                    params={"business_key": "ORD-1001"}).json()
    assert ra["total"] == 1 and rb["total"] == 1
    assert ra["items"][0]["payload"]["customer"] == "Alpha 客户甲"
    assert rb["items"][0]["payload"]["customer"] == "Beta 客户甲"

    # Full record sets never leak across the boundary.
    all_a = client.get("/api/records", headers=alpha_headers).json()
    all_b = client.get("/api/records", headers=beta_headers).json()
    assert all_a["total"] == 3 and all_b["total"] == 5
    assert {r["workspace_id"] for r in all_a["items"]} == {"ws-alpha"}
    assert {r["workspace_id"] for r in all_b["items"]} == {"ws-beta"}


def test_error_and_download_endpoints_are_workspace_scoped(
    client, alpha_headers, beta_headers, mapping, alpha_file, beta_file,
    uploader, wait_terminal,
):
    t1 = uploader(client, alpha_headers, "REQ-FILES", alpha_file, mapping).json()["task"]
    t2 = uploader(client, beta_headers, "REQ-FILES", beta_file, mapping).json()["task"]
    wait_terminal(client, alpha_headers, t1["id"])
    wait_terminal(client, beta_headers, t2["id"])

    # Error file exists (alpha has invalid rows).
    ok = client.get(f"/api/imports/{t1['id']}/errors", headers=alpha_headers)
    assert ok.status_code == 200 and "row_number" in ok.content.decode("utf-8-sig")

    # Cross-workspace access to error file and source download -> 404.
    assert client.get(f"/api/imports/{t2['id']}/errors",
                      headers=alpha_headers).status_code == 404
    assert client.get(f"/api/imports/{t1['id']}/download",
                      headers=beta_headers).status_code == 404

    # Same-workspace source download works.
    dl = client.get(f"/api/imports/{t1['id']}/download", headers=alpha_headers)
    assert dl.status_code == 200 and b"ORD-1001" in dl.content


# ---------------------------------------------------------------------------
# Idempotency vs conflict, scoped by workspace
# ---------------------------------------------------------------------------

def test_identical_request_is_reused(
    client, alpha_headers, mapping, alpha_file, uploader,
):
    first = uploader(client, alpha_headers, "REQ-IDEM", alpha_file, mapping)
    assert first.status_code == 201 and first.json()["reused"] is False
    files_after_first = set((config.STORAGE_DIR / "ws-alpha" / "uploads").glob("*"))
    assert len(files_after_first) == 1
    second = uploader(client, alpha_headers, "REQ-IDEM", alpha_file, mapping)
    assert second.status_code == 200
    assert second.json()["reused"] is True
    assert second.json()["task"]["id"] == first.json()["task"]["id"]

    # Reuse discarded the duplicate upload: still exactly one stored file.
    files_after_second = set((config.STORAGE_DIR / "ws-alpha" / "uploads").glob("*"))
    assert files_after_second == files_after_first


def test_different_content_same_request_id_conflicts(
    client, alpha_headers, mapping, alpha_file, beta_file, uploader,
):
    uploader(client, alpha_headers, "REQ-CONF", alpha_file, mapping)
    # beta's file has the same filename but different content
    r = uploader(client, alpha_headers, "REQ-CONF", beta_file, mapping)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["same_hash"] is False
    assert detail["same_mapping"] is True
    assert detail["existing_task_id"]


def test_different_mapping_same_file_conflicts(
    client, alpha_headers, mapping, alpha_file, uploader,
):
    uploader(client, alpha_headers, "REQ-MAP", alpha_file, mapping)
    changed = dict(mapping)
    changed["remark"] = "customer"  # deliberately different target
    r = uploader(client, alpha_headers, "REQ-MAP", alpha_file, changed)
    assert r.status_code == 409
    assert r.json()["detail"]["same_mapping"] is False


def test_same_request_id_in_other_workspace_is_independent(
    client, alpha_headers, beta_headers, mapping, alpha_file, uploader,
    wait_terminal,
):
    a = uploader(client, alpha_headers, "REQ-SHARED-ID", alpha_file, mapping)
    b = uploader(client, beta_headers, "REQ-SHARED-ID", alpha_file, mapping)
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["task"]["id"] != b.json()["task"]["id"]
    wait_terminal(client, alpha_headers, a.json()["task"]["id"])
    wait_terminal(client, beta_headers, b.json()["task"]["id"])
    assert client.get("/api/records", headers=alpha_headers).json()["total"] == 3
    assert client.get("/api/records", headers=beta_headers).json()["total"] == 3


# ---------------------------------------------------------------------------
# Cancellation & cleanup only touch the task's own files
# ---------------------------------------------------------------------------

def test_cancel_and_cleanup_isolation(
    client, alpha_headers, beta_headers, mapping, alpha_file, beta_file,
    uploader, wait_terminal,
):
    # ROW_DELAY is 0 in tests, so cancellation is validated via the API
    # contract on a finished task plus a dedicated slow test elsewhere;
    # here verify delete semantics and cross-workspace 404 on delete.
    ta = uploader(client, alpha_headers, "REQ-DEL-A", alpha_file, mapping).json()["task"]
    tb = uploader(client, beta_headers, "REQ-DEL-B", beta_file, mapping).json()["task"]
    wait_terminal(client, alpha_headers, ta["id"])
    wait_terminal(client, beta_headers, tb["id"])

    # Cannot delete across the boundary.
    assert client.delete(f"/api/imports/{tb['id']}",
                         headers=alpha_headers).status_code == 404

    storage_before = [p for p in (config.STORAGE_DIR / "ws-alpha").rglob("*")
                      if p.is_file()]
    assert storage_before  # alpha task owns upload + error files
    r = client.delete(f"/api/imports/{ta['id']}", headers=alpha_headers)
    assert r.status_code == 200 and r.json()["deleted"] == ta["id"]

    # Task row and its records gone; beta data untouched.
    assert client.get(f"/api/imports/{ta['id']}", headers=alpha_headers).status_code == 404
    assert client.get("/api/records", headers=alpha_headers).json()["total"] == 0
    beta_records = client.get("/api/records", headers=beta_headers).json()
    assert beta_records["total"] == 5

    # Only alpha files belonging to this task were removed; beta files remain.
    assert not [p for p in storage_before if p.exists()]
    assert list((config.STORAGE_DIR / "ws-beta" / "uploads").glob("*"))


def test_delete_running_task_is_rejected(
    client, alpha_headers, mapping, alpha_file, uploader, monkeypatch,
):
    # Force a slow worker so the task is still running when we delete.
    from app.services import importer
    monkeypatch.setattr(importer.config, "ROW_DELAY_SECONDS", 0.3)
    t = uploader(client, alpha_headers, "REQ-RUN", alpha_file, mapping).json()["task"]
    import time
    for _ in range(25):
        status = client.get(f"/api/imports/{t['id']}", headers=alpha_headers).json()["status"]
        if status == "running":
            break
        time.sleep(0.02)
    r = client.delete(f"/api/imports/{t['id']}", headers=alpha_headers)
    assert r.status_code == 409

    # Cancel it, wait for terminal state, then cleanup succeeds.
    client.post(f"/api/imports/{t['id']}/cancel", headers=alpha_headers)
    for _ in range(50):
        status = client.get(f"/api/imports/{t['id']}", headers=alpha_headers).json()["status"]
        if status == "cancelled":
            break
        time.sleep(0.02)
    assert client.delete(f"/api/imports/{t['id']}",
                         headers=alpha_headers).status_code == 200


# ---------------------------------------------------------------------------
# Preview & mapping validation
# ---------------------------------------------------------------------------

def test_preview_returns_headers_and_suggested_mapping(client, alpha_headers, alpha_file):
    with open(alpha_file, "rb") as fh:
        r = client.post(
            "/api/imports/preview",
            headers=alpha_headers,
            files={"file": ("orders.csv", fh, "text/csv")},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["headers"] == ["order_id", "customer", "amount", "remark"]
    assert len(body["rows"]) == 5
    assert body["suggested_mapping"]["order_id"] == "order_id"


def test_mapping_unknown_column_rejected(client, alpha_headers, alpha_file):
    with open(alpha_file, "rb") as fh:
        r = client.post(
            "/api/imports",
            headers=alpha_headers,
            data={"request_id": "REQ-BAD-MAP",
                  "mapping": json.dumps({"nope": "order_id"})},
            files={"file": ("orders.csv", fh, "text/csv")},
        )
    assert r.status_code == 400
    assert "nope" in r.json()["detail"]


def test_mapping_missing_required_field_rejected(client, alpha_headers, alpha_file):
    bad = {"customer": "customer", "amount": "amount"}
    with open(alpha_file, "rb") as fh:
        r = client.post(
            "/api/imports",
            headers=alpha_headers,
            data={"request_id": "REQ-MISSING", "mapping": json.dumps(bad)},
            files={"file": ("orders.csv", fh, "text/csv")},
        )
    assert r.status_code == 400 and "order_id" in r.json()["detail"]
