#!/usr/bin/env python3 -I
"""End-to-end live verification of workspace isolation.

Run while the backend (uvicorn) is up on 127.0.0.1:8000.
Uses ONLY the public HTTP API, with the untrusted sample CSVs passed by path.

Scenario:
  1. header enforcement (400 / 403)
  2. two parallel imports, same filename + same request_id, overlapping keys
  3. mid-run workspace switch: the other workspace's batch id -> 404,
     while the original task keeps progressing untouched
  4. idempotent reuse (200) vs content conflict (409)
  5. overlapping business key ORD-1001 holds different payloads per workspace
  6. error file + source download are workspace scoped
  7. cancel + cleanup only affect the task's own workspace/files
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
SAMPLE_A = ROOT / "samples" / "ws-alpha" / "orders.csv"
SAMPLE_B = ROOT / "samples" / "ws-beta" / "orders.csv"
MAPPING = {"order_id": "order_id", "customer": "customer",
           "amount": "amount", "remark": "remark"}

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def wait_terminal(client: httpx.Client, ws: str, task_id: int, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/imports/{task_id}", headers={"X-Workspace-Id": ws})
        body = r.json()
        if body["status"] not in ("pending", "running"):
            return body
        time.sleep(0.2)
    raise TimeoutError(f"task {task_id} in {ws} never finished")


def create_import(client: httpx.Client, ws: str, request_id: str, sample: Path) -> httpx.Response:
    with sample.open("rb") as fh:
        return client.post(
            "/api/imports",
            headers={"X-Workspace-Id": ws},
            data={"request_id": request_id, "mapping": json.dumps(MAPPING)},
            files={"file": (sample.name, fh, "text/csv")},
        )


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        print("== 1. 请求头强制 ==")
        check("无 X-Workspace-Id -> 400",
              client.get("/api/imports").status_code == 400)
        check("未知工作区 -> 403",
              client.get("/api/imports", headers={"X-Workspace-Id": "ws-evil"}).status_code == 403)
        ws_ids = {w["id"] for w in client.get("/api/workspaces").json()}
        check("演示账号可见两个工作区", ws_ids == {"ws-alpha", "ws-beta"}, str(ws_ids))

        print("== 2. 同名文件 + 同 request_id 并行导入（主键重叠）==")
        ra = create_import(client, "ws-alpha", "REQ-LIVE", SAMPLE_A)
        rb = create_import(client, "ws-beta", "REQ-LIVE", SAMPLE_B)
        check("alpha 创建 201", ra.status_code == 201, ra.text)
        check("beta 创建 201", rb.status_code == 201, rb.text)
        ta, tb = ra.json()["task"], rb.json()["task"]
        check("同编号在两工作区生成不同任务", ta["id"] != tb["id"])
        check("任务记录创建时工作区", ta["workspace_id"] == "ws-alpha" and tb["workspace_id"] == "ws-beta")
        check("任务记录创建时映射", ta["mapping"] == MAPPING)

        print("== 3. 执行中途切换工作区：跨区引用 404，原任务继续跑 ==")
        time.sleep(0.6)  # let both workers process a couple of rows
        mid_a = client.get(f"/api/imports/{ta['id']}", headers={"X-Workspace-Id": "ws-alpha"}).json()
        check("alpha 任务执行中有进度", mid_a["status"] == "running" and mid_a["processed_rows"] > 0,
              str(mid_a["status"]))
        cross = client.get(f"/api/imports/{ta['id']}", headers={"X-Workspace-Id": "ws-beta"})
        check("beta 头访问 alpha 任务 -> 404", cross.status_code == 404, cross.text)
        cross2 = client.get(f"/api/imports/{tb['id']}", headers={"X-Workspace-Id": "ws-alpha"})
        check("alpha 头访问 beta 任务 -> 404", cross2.status_code == 404, cross2.text)
        time.sleep(1.0)
        progressed = client.get(f"/api/imports/{ta['id']}", headers={"X-Workspace-Id": "ws-alpha"}).json()
        check("被跨区访问后 alpha 任务仍在推进",
              progressed["processed_rows"] > mid_a["processed_rows"],
              f"{mid_a['processed_rows']} -> {progressed['processed_rows']}")

        fa = wait_terminal(client, "ws-alpha", ta["id"])
        fb = wait_terminal(client, "ws-beta", tb["id"])
        check("alpha 成功 3 / 失败 3", (fa["success_rows"], fa["failed_rows"]) == (3, 3), str(fa))
        check("beta 成功 5 / 失败 1", (fb["success_rows"], fb["failed_rows"]) == (5, 1), str(fb))

        print("== 4. 幂等复用 vs 内容冲突 ==")
        reuse = create_import(client, "ws-alpha", "REQ-LIVE", SAMPLE_A)
        check("同文件同映射重复提交 -> 200 reused",
              reuse.status_code == 200 and reuse.json()["reused"] is True, reuse.text)
        conflict = create_import(client, "ws-alpha", "REQ-LIVE", SAMPLE_B)
        check("同编号不同内容 -> 409", conflict.status_code == 409, conflict.text)
        check("409 指明文件内容不同", conflict.json()["detail"]["same_hash"] is False)

        print("== 5. 重叠主键 ORD-1001 两边独立 ==")
        ka = client.get("/api/records", headers={"X-Workspace-Id": "ws-alpha"},
                        params={"business_key": "ORD-1001"}).json()
        kb = client.get("/api/records", headers={"X-Workspace-Id": "ws-beta"},
                        params={"business_key": "ORD-1001"}).json()
        check("alpha 的 ORD-1001 是 Alpha 客户甲",
              ka["items"][0]["payload"]["customer"] == "Alpha 客户甲", str(ka))
        check("beta 的 ORD-1001 是 Beta 客户甲",
              kb["items"][0]["payload"]["customer"] == "Beta 客户甲", str(kb))

        print("== 6. 错误文件与下载同样按工作区隔离 ==")
        check("alpha 错误文件可下载",
              client.get(f"/api/imports/{ta['id']}/errors",
                         headers={"X-Workspace-Id": "ws-alpha"}).status_code == 200)
        check("跨区取错误文件 -> 404",
              client.get(f"/api/imports/{tb['id']}/errors",
                         headers={"X-Workspace-Id": "ws-alpha"}).status_code == 404)
        check("跨区下载源文件 -> 404",
              client.get(f"/api/imports/{ta['id']}/download",
                         headers={"X-Workspace-Id": "ws-beta"}).status_code == 404)

        print("== 7. 取消与清理只处理本任务 ==")
        rc = create_import(client, "ws-alpha", "REQ-CANCEL", SAMPLE_A)
        tc = rc.json()["task"]
        time.sleep(0.5)
        cancel = client.post(f"/api/imports/{tc['id']}/cancel",
                             headers={"X-Workspace-Id": "ws-alpha"})
        check("取消接口 200", cancel.status_code == 200, cancel.text)
        fc = wait_terminal(client, "ws-alpha", tc["id"])
        check("任务最终为 cancelled", fc["status"] == "cancelled", fc["status"])
        deleted = client.delete(f"/api/imports/{tc['id']}",
                                headers={"X-Workspace-Id": "ws-alpha"})
        check("清理本任务 200", deleted.status_code == 200, deleted.text)
        check("清理后详情 404",
              client.get(f"/api/imports/{tc['id']}",
                         headers={"X-Workspace-Id": "ws-alpha"}).status_code == 404)
        check("beta 任务与记录不受影响",
              client.get("/api/records",
                         headers={"X-Workspace-Id": "ws-beta"}).json()["total"] == 5)
        check("跨区清理 -> 404",
              client.delete(f"/api/imports/{tb['id']}",
                            headers={"X-Workspace-Id": "ws-alpha"}).status_code == 404)

    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
