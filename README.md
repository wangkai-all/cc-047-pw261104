# 多工作区 CSV 导入演示（FastAPI + SQLite + React）

一个本地演示账号（`demo-account`，无真实鉴权系统）可访问两个工作区
`ws-alpha` / `ws-beta`。所有数据操作都必须在请求头显式携带
`X-Workspace-Id`，服务端逐请求核对工作区归属与资源归属。

## 隔离规则（本演示要证明的事）

1. **每个请求显式带工作区**：数据接口全部依赖 `require_workspace`，
   缺头返回 400，未知工作区返回 403。
2. **服务端核对资源归属**：所有任务/记录/文件查询都带
   `WHERE workspace_id = ?`。把另一个工作区的批次编号带进来一律
   **404 找不到**（与"编号不存在"表现一致，不泄露对方资源是否存在）。
   列表、详情、错误文件、原始文件下载规则相同。
3. **页面切换只影响之后发起的请求**：前端把当前工作区存在本地，
   仅作为后续请求的 `X-Workspace-Id`；不会中断或改写任何已创建的任务。
4. **任务在创建时固定工作区与字段映射**：写入 `import_tasks` 行后，
   后台 worker 只从数据库读这行记录，不再读取任何"页面当前选择"。
5. **同工作区幂等**：相同 `request_id` + 相同文件哈希 + 相同映射 →
   复用原任务（HTTP 200，`reused: true`）；文件或映射任一不同 → 409 冲突。
6. **跨工作区同编号互不影响**：唯一约束是
   `UNIQUE(workspace_id, request_id)`，记录主键是
   `UNIQUE(workspace_id, business_key)`，两边可用相同编号、相同业务主键。
7. **取消与清理只处理本任务的文件**：物理存储按
   `storage/<workspace>/...` 分目录，删除只 unlink 本任务的上传文件与错误文件。

## 目录结构

```
backend/            FastAPI 应用
  app/main.py       路由（全部经 require_workspace 收口）
  app/deps.py       X-Workspace-Id 校验
  app/db.py         SQLite 连接与建表（WAL）
  app/services/     CSV 解析、导入 worker、幂等/冲突、取消清理
  tests/            15 个 pytest 用例
frontend/           React + Vite SPA（vite 代理 /api → :8000）
samples/            两个工作区各一份同名 orders.csv，主键重叠且含非法行
scripts/            启动/重置/线上验证脚本（与样本数据目录隔离）
data/               运行时生成：app.db + storage/（已 gitignore）
```

## 启动

```bash
# 终端 1：后端（首次自动建 venv 装依赖）
bash scripts/run_backend.sh

# 终端 2：前端（首次自动 npm install）
bash scripts/run_frontend.sh
# 打开 http://127.0.0.1:5173
```

后端 API 文档：http://127.0.0.1:8000/docs

重置演示数据：`bash scripts/reset_data.sh`

## 页面演示走查（对应需求场景）

1. 在 **Alpha 工作区** 选 `samples/ws-alpha/orders.csv`，确认预览和建议映射，
   请求编号填 `REQ-DEMO`，点"创建导入任务"。
2. 立刻切到 **Beta 工作区**，选同名文件 `samples/ws-beta/orders.csv`，
   同样用 `REQ-DEMO` 创建。两边同时后台执行（每行 0.4s，可观察进度条）。
3. **执行中途切回 Alpha → 打开任务详情**，再切到 Beta：
   详情用新工作区头重新请求同一编号 → 页面显示 404；
   切回 Alpha 又能看到任务仍在推进。详情页同时展示
   "任务创建时所属工作区"与"当前页面工作区"用于逐条核对。
4. 进"已导入记录"页，按业务编号 `ORD-1001` 过滤：
   Alpha 看到 `Alpha 客户甲`，Beta 看到 `Beta 客户甲`，没有串写。
5. 在 Alpha 用 `REQ-DEMO` 再传一次同一文件 → 提示复用；
   改传 Beta 的文件（同名不同内容）→ 409 冲突并指出"文件内容不同"。
6. Alpha 任务详情下载错误行 CSV（含金额非法、客户为空、负金额行）；
   用 Beta 头请求 Alpha 的错误文件/源文件 → 404。
7. 新建一个任务后点"取消任务"，终态后点"清理任务与文件"：
   仅本任务的记录与文件被删除，Beta 数据原样保留。

## 自动化验证

```bash
# 后端单元/接口测试（独立临时数据库，自动清理）
.venv/bin/python -m pytest backend/tests -q

# 线上端到端：需先启动后端，覆盖并行导入、中途切换 404、
# 幂等/冲突、重叠主键、下载隔离、取消清理共 28 项断言
.venv/bin/python -I scripts/verify_live.py
```

## 样本数据说明

| 文件 | 有效行 | 非法行 | 与对方重叠的主键 |
| --- | --- | --- | --- |
| `samples/ws-alpha/orders.csv` | ORD-1001/1002/1004 | 金额非法、客户为空、负金额 | ORD-1001、ORD-1002 |
| `samples/ws-beta/orders.csv` | ORD-1001/1002/1007/1009/1010 | 金额缺失 | ORD-1001、ORD-1002 |

上传文件按不可信数据处理：大小限制 5MB，仅通过 `csv` 模块读取，
物理目录与代码目录分离，验证脚本以 `python -I` 运行且只按路径传文件。
