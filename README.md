# 离散制造车间生产管理系统（MES 方向）

> 面向离散制造场景的车间生产管理系统，覆盖
> **生产工单 → 工序报工 → 设备数采 → 质量检验（SPC）→ 库存联动 → 统计报表 → 权限控制**
> 完整业务闭环。
>
> 技术栈：**Python · FastAPI · MySQL · Redis · Vue3 · ECharts · Docker Compose**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3.5-42b883)](https://vuejs.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)](./LICENSE)

---

## 目录

* [一、项目背景](#一项目背景)
* [二、功能清单](#二功能清单)
* [三、简历描述 × 已实现功能 逐条对照](#三简历描述--已实现功能-逐条对照)
* [四、技术架构与实现方案](#四技术架构与实现方案)
* [五、目录结构](#五目录结构)
* [六、快速开始](#六快速开始)
* [七、测试](#七测试)
* [八、接口文档](#八接口文档)
* [九、演示数据](#九演示数据)
* [十、文档索引](#十文档索引)

---

## 一、项目背景

离散制造（多品种、小批量、工艺路线多变）的车间现场，普遍存在三类痛点：

1. **工单状态靠人工维护**：口头下达、纸质流转，状态不一致导致排产失真；
   重复报工更是直接产生脏数据，计划量与完成量对不上。
2. **设备状态黑盒**：设备是否在运行、稼动率多少，只能事后统计，
   管理者看到的永远是"昨天的数据"。
3. **质量靠事后全检**：缺少过程控制手段，异常发现往往滞后一整批。

本项目按 MES（Manufacturing Execution System）的标准分层，
用**工单状态机 + 事务与幂等**解决数据准确性，
用**设备数采 + Redis 缓存 + SSE 推送**解决实时性，
用 **SPC X̄-R 控制图 + 自动判异**解决质量前置预警，
并用 **RBAC 接口级权限**保证三类角色各司其职。

---

## 二、功能清单

| 模块 | 功能点 |
| --- | --- |
| 生产工单 | 工单创建（按 BOM 展开物料需求）、状态机流转、工序报工、超量拦截、末工序自动完工 |
| 幂等与事务 | 应用层幂等快照 + 数据库唯一约束**双层防护**，杜绝重复报工 |
| 设备数采 | 模拟网关定时上报运行数据、Redis 缓存实时状态、SSE 秒级推送看板 |
| 质量管理 | SPC X̄-R 控制图（8 条判异准则）、控制限自动重算、异常批次自动生成待处理质检单 |
| 库存管理 | 发料 / 退料 / 盘点、报工自动扣减、库存不足整笔回滚、安全库存预警 |
| 统计报表 | 工单进度、良品率、设备稼动率、产量日报、工序效率、不良柏拉图、库存周转、人员绩效（8 张） |
| 权限控制 | 21 个权限点 / 3 类角色 / 接口级鉴权（管理员、班组长、操作工） |
| 前端看板 | Vue3 + ECharts 九大页面，SSE 实时刷新，按钮按可流转状态动态渲染 |

---

## 三、简历描述 × 已实现功能 逐条对照

> 每条均给出**代码位置**，可逐项核对，不做夸大。

| # | 简历描述 | 实现情况 | 代码位置 |
| --- | --- | --- | --- |
| 1 | 技术栈 Python · FastAPI · MySQL · Redis · Vue3 · ECharts · Docker Compose | 全部真实使用：后端 FastAPI + SQLAlchemy（MySQL 8，可切 SQLite）；Redis 缓存设备实时状态；前端 Vue3 + Vite + ECharts；`docker-compose.yml` 编排 MySQL 8 + Redis 7 + API | `backend/app/`、`frontend/`、`docker-compose.yml` |
| 2 | FastAPI **三层架构**（路由 / 服务 / 数据访问） | `api/` 只做参数校验与响应包装；`services/` 承载全部业务规则；`repositories/` + `models/` 负责数据访问。层间禁止反向依赖 | `backend/app/api/`、`app/services/`、`app/repositories/` |
| 3 | 使用 **SQLAlchemy + MySQL**，设计 **20+ 张业务表** | 实际 **31 张表**（权限 5 + 主数据 12 + 库存 3 + 工单 4 + 质量 4 + 设备 2 + 系统 1），文档由元数据自动生成 | `backend/app/models/`、`docs/数据库设计.md` |
| 4 | **工单状态机流转** | 状态流转表是唯一真源；非法流转抛 `StateConflictError`；前端按钮由后端返回的可流转状态驱动 | `app/models/order.py::WORK_ORDER_TRANSITIONS`、`app/services/order_service.py` |
| 5 | 状态流转加**事务与幂等控制**，防止重复报工产生脏数据 | 一次报工 = 一个事务（报工流水 + 库存扣减 + SPC 子组 + 质检单 + 工单完工），任一失败整笔回滚；幂等为**双层**：① 应用层 `sys_idempotency` 请求指纹 + 响应快照；② `pp_work_report` 唯一约束 `uk_pp_report_idempotency` | `app/core/idempotency.py`、`app/db/unit_of_work.py`、`app/services/order_service.py::report_work` |
| 6 | 模拟**设备数采网关**定时上报运行数据 | 后台任务每 3 秒（`GATEWAY_INTERVAL_SEC`）采集一次全量设备帧并落 `eq_status_log`，固定随机种子可复现 | `app/realtime/device_gateway.py` |
| 7 | **Redis 缓存设备实时状态** | 设备快照写入 Redis（TTL 600s），看板接口优先读缓存，避免全表扫描；Redis 不可用时自动降级为进程内内存实现，接口语义一致 | `app/realtime/redis_client.py` |
| 8 | **SSE** 向前端推送，车间看板**秒级刷新** | `EventSource` 长连接，每 2 秒（`SSE_PUSH_INTERVAL_SEC`）推送一帧，15 秒心跳；Nginx 配置对该路径关闭 `proxy_buffering` | `app/realtime/sse_hub.py`、`app/api/v1/dashboard.py::stream`、`deploy/nginx.conf` |
| 9 | 按 **SPC** 思路实现**均值-极差控制图（X̄-R 图）**计算与超限告警 | 纯函数实现：A₂/D₃/D₄/d₂ 系数表（n=2~10）；X̄ 图 `UCL/LCL = X̄̄ ± A₂·R̄`；R 图 `D₄·R̄ / D₃·R̄`；`σ̂ = R̄/d₂`；`Cp / Cpk` | `app/services/spc_core.py` |
| 10 | **ECharts 可视化** | X̄ 图与 R 图叠加 CL/UCL/LCL `markLine`，超限点红色高亮，判异清单联动 | `frontend/src/views/SpcView.vue`、`frontend/standalone/views.js` |
| 11 | 异常批次**自动生成待处理质检单** | 报工或录入子组时命中判异 → 在同一事务内生成 `PENDING` 质检单 | `app/services/spc_service.py::record_subgroup` |
| 12 | **GB/T 4091 判异准则** | 完整实现 8 条（默认启用 1/2/3/5/6，可配置 `SPC_RULE_SET`） | `app/services/spc_core.py::detect_violations` |
| 13 | **多表关联 SQL** 实现 8 张统计报表 | 工单进度、良品率、设备稼动率、产量日报、工序工时效率、不良柏拉图、库存周转、人员绩效，均为 SQL 聚合而非内存拼接 | `app/services/report_service.py` |
| 14 | 基于 **RBAC** 实现**接口级权限控制**（管理员 / 班组长 / 操作工） | 21 个权限点 → 3 个角色 → FastAPI 依赖 `require_permissions(...)` 挂在具体路由上；令牌解析后**回源复核**用户状态 | `app/core/rbac.py`、`app/core/permission_catalog.py` |
| 15 | **40+ 个单元测试**覆盖工单流转、库存扣减等关键路径 | 实际 **82 个** pytest 用例，全部通过；覆盖状态机、幂等、报工、库存、SPC、RBAC、网关/SSE、API 契约 | `backend/tests/`（9 个文件） |
| 16 | **Docker Compose 一键部署** | `docker compose up -d --build` 起 MySQL 8 + Redis 7 + API(+前端)，seeder 服务自动写示例数据；另附单容器 SQLite 轻量版 | `docker-compose.yml`、`docker-compose.lite.yml`、`backend/Dockerfile` |
| 17 | 接口文档由 **Swagger 自动生成**并手写补充示例 | FastAPI 自动生成 OpenAPI 3.1（`/docs`、`/redoc`）；另手写统一约定、业务语义、错误码、手搓 curl 示例 | `docs/接口文档.md` |

### 量化指标核对

| 指标 | 简历口径 | 本仓库实测 | 核对命令 |
| --- | --- | --- | --- |
| 业务表数量 | 20+ 张 | **31 张** | `python -m scripts.gen_table_doc` |
| 单元测试 | 40+ 个 | **82 个** | `bash scripts/test.sh` |
| 统计报表 | 8 张 | **8 张** | `GET /api/v1/reports` |
| 权限点 / 角色 | — / 3 类 | **21 / 3** | `app/core/permission_catalog.py` |
| 判异准则 | — | **8 条**（GB/T 4091） | `GET /api/v1/quality/spc/rules` |
| 看板刷新 | 秒级 | **2 秒/帧** | `SSE_PUSH_INTERVAL_SEC=2` |
| 后端代码量 | — | 约 9,100 行 Python | `find backend -name "*.py" \| xargs wc -l` |
| 前端代码量 | — | 约 4,000 行（Vue/JS/CSS） | — |

---

## 四、技术架构与实现方案

### 4.1 分层架构

```
┌──────────────────────────────────────────────────────────────┐
│  Vue3 + Vite + Pinia + Vue Router + ECharts                  │
│  看板 / 工单 / 报工 / 设备 / SPC / 质检 / 库存 / 报表         │
│            ↑ REST (JWT)              ↑ SSE (text/event-stream)│
├──────────────────────────────────────────────────────────────┤
│  API 层        app/api/v1/*    参数校验 · 权限依赖 · 响应包装 │
│  Service 层    app/services/*  业务规则 · 事务边界 · 状态机   │
│  Data 层       app/models/* + repositories/*  SQLAlchemy ORM  │
├──────────────────────────────────────────────────────────────┤
│  MySQL 8 / SQLite      Redis 7 / 内存降级                     │
│  31 张业务表            设备状态缓存 · 幂等 key · pub/sub      │
└──────────────────────────────────────────────────────────────┘
              ↑ 定时上报（3s）
       模拟设备数采网关 app/realtime/device_gateway.py
```

### 4.2 关键设计决策

**① 双层幂等（为什么不用单层？）**

只靠应用层快照：并发请求可能同时通过检查，双双落库。
只靠唯一约束：能挡住重复，但无法"回放首次结果"，调用方拿不到幂等响应。
因此设计为：先查 `sys_idempotency`（命中 `SUCCEEDED` 直接回放快照、命中
`IN_PROGRESS` 返回 409），未命中则执行业务并依赖
`uk_pp_report_idempotency` 唯一约束兜底。**两层互为保险**。

**② 状态机单一真源**

流转表 `WORK_ORDER_TRANSITIONS` 定义在模型层，服务层校验与
`GET /orders/{id}/allowed-transitions` 接口读取的是同一份数据，
前端按钮因此永远不会出现"能点但会被拒"的情况。

**③ 库存扣减的行级锁**

`locking.py` 对 `mm_inventory_stock` 目标行加行锁后再判断可用量，
避免在并发发料下出现超发；不足则抛 `InventoryShortageError` 让整笔事务回滚，
绝不允许出现负库存。

**④ Redis 自动降级**

`RedisCache` 在连接失败时把 `_redis` 置空并切换到 `_MemoryBackend`
（带过期时间的进程内 KV + pub/sub）。上层代码完全无感，
保证"没有 Redis 也能完整演示"——这也是本仓库能在任何机器上跑起来的原因。

**⑤ SPC 算法纯函数化**

`spc_core.py` 不依赖数据库、不依赖框架，输入样本输出控制限与判异结果。
好处是可单测（15 个用例只测算法）、可离线试算（`/spc/analyze` 不落库）、
可复用到任何工序。

### 4.3 工单状态机

```
DRAFT ──下达──> RELEASED ──开工──> IN_PROGRESS ──完工──> COMPLETED
  │                │                   │
  └──────取消──────┴───────取消────────┴──────────────> CANCELLED

IN_PROGRESS ──暂停──> PAUSED ──恢复──> IN_PROGRESS
```

### 4.4 一次报工的事务边界

```
[BEGIN]
  1. 校验工单状态 / 工序状态
  2. 校验累计量 ≤ 计划量                 → 超出：StateConflictError
  3. INSERT pp_work_report（唯一约束兜底）→ 重复：DuplicateReportError
  4. 按 BOM 扣减 mm_inventory_stock（行锁）→ 不足：InventoryShortageError
  5. 写入 qm_spc_subgroup 并执行判异
  6. 命中判异 → INSERT qm_inspection_task(PENDING)
  7. 末工序报满 → 工单自动 IN_PROGRESS → COMPLETED
[COMMIT]  —— 任一步失败则整笔 ROLLBACK
```

---

## 五、目录结构

```
离散制造车间生产管理系统/
├── README.md                      # 本文件
├── LICENSE                        # Apache-2.0
├── .gitignore
├── .env.example                   # 环境变量模板
├── .dockerignore
├── docker-compose.yml             # 完整编排：MySQL8 + Redis7 + API(+前端) + seeder [+nginx]
├── docker-compose.lite.yml        # 轻量编排：单容器 + SQLite（无需 MySQL/Redis）
│
├── backend/
│   ├── Dockerfile                 # 多阶段：node 构建前端 → python 运行后端
│   ├── requirements.txt
│   ├── pytest.ini
│   └── app/
│       ├── main.py                # 应用入口 · 生命周期 · 异常处理器 · 静态前端挂载
│       ├── core/                  # config / security(JWT+PBKDF2) / rbac / idempotency
│       │                          # response(统一响应体) / exceptions(业务异常) / permission_catalog
│       ├── db/                    # session(MySQL/SQLite 双模) / unit_of_work(事务)
│       ├── models/                # 31 张业务表 ORM（rbac / master / inventory / order / quality / equipment / system）
│       ├── repositories/          # 数据访问层
│       ├── schemas/               # Pydantic 入参出参
│       ├── services/              # 业务层：order / inventory / quality / spc_core / spc /
│       │                          # report / dashboard / auth / locking
│       ├── realtime/              # redis_client(含内存降级) / sse_hub / device_gateway
│       └── api/v1/                # auth / master / orders / quality / inventory / dashboard / reports
│   ├── scripts/
│   │   ├── seed.py                # 示例数据播种（固定随机种子，可复现）
│   │   └── gen_table_doc.py       # 从 ORM 元数据生成数据库设计文档
│   └── tests/                     # 82 个单元测试（9 个文件）
│
├── frontend/
│   ├── package.json / vite.config.js / index.html
│   ├── src/                       # Vue3 工程源码（Vite 构建）
│   │   ├── api/                   # request.js（fetch 封装）/ modules.js
│   │   ├── components/            # StatCard / DataTable / StatusTag / ChartBox
│   │   ├── views/                 # Login / Dashboard / Orders / ReportWork /
│   │   │                          # Equipment / Spc / Quality / Inventory / Reports
│   │   ├── router / store / utils / styles
│   ├── standalone/                # 免构建演示版（importmap + 本地 vendor，零 npm 依赖）
│   └── dist/                      # Vite 构建产物（生产使用）
│
├── deploy/
│   ├── nginx.conf                 # 可选反向代理（SSE 关闭缓冲）
│   └── mysql/init.sql             # MySQL 首次初始化
│
├── scripts/                       # 启动 / 播种 / 测试 / 一键部署脚本（sh + bat）
└── docs/
    ├── 数据库设计.md              # 自动生成（31 张表）
    ├── 接口文档.md                # Swagger 自动 + 手写补充
    ├── 部署文档.md
    └── 用户操作手册.md
```

---

## 六、快速开始

### 方式一：Docker Compose（推荐，一键）

```bash
git clone <repo-url>
cd discrete-manufacturing-mes

bash scripts/docker-up.sh          # Windows: scripts\docker-up.bat
# 或：docker compose up -d --build

# 打开 http://localhost:8000/  ，账号 admin / leader / worker，口令 mes@2026
```

### 方式二：轻量单容器（无需 MySQL / Redis）

```bash
bash scripts/docker-up.sh lite     # Windows: scripts\docker-up.bat lite
```

### 方式三：本地直跑（开发调试）

```bash
bash scripts/start.sh              # Windows: scripts\start.bat    启动 API（默认 SQLite）
bash scripts/seed.sh               # Windows: scripts\seed.bat     写入示例数据
# 打开 http://localhost:8000/
```

前端开发模式（热更新，需 Node 18+）：

```bash
cd frontend && npm install && npm run dev     # http://localhost:5173，已代理 /api → 8000
```

> **免构建前端**：若不想装 Node，设置 `FRONTEND_PREFER=standalone`，
> 后端会直接提供 `frontend/standalone/` 版本（功能一致，仅样式略简）。

---

## 七、测试

```bash
bash scripts/test.sh                          # 全部 82 个用例
bash scripts/test.sh -k idempotency           # 只跑幂等相关
bash scripts/test.sh tests/test_spc_core.py   # 只跑 SPC 算法
```

测试使用**临时 SQLite** 文件，每个用例独立建库，不污染本地数据，也不需要外部服务。

| 测试文件 | 覆盖内容 |
| --- | --- |
| `test_spc_core.py` | X̄-R 控制限、Cp/Cpk、8 条判异准则（15 例） |
| `test_order_state_machine.py` | 合法/非法流转、可流转状态计算 |
| `test_work_report.py` | 报工事务、超量拦截、SPC 联动、重复报工标识 |
| `test_idempotency.py` | 幂等快照回放、请求指纹冲突、并发 IN_PROGRESS |
| `test_inventory.py` | 发料/退料/盘点、库存不足回滚、流水留痕 |
| `test_rbac.py` | 三类角色的接口级放行与拦截 |
| `test_reports.py` | 8 张报表 SQL 聚合正确性 |
| `test_device_gateway.py` | 网关采集帧、SSE Hub 背压、缓存后端降级 |
| `test_api_contract.py` | 统一响应体、鉴权、健康检查契约 |

---

## 八、接口文档

启动后自动可用：

* Swagger UI：<http://localhost:8000/docs>
* ReDoc：<http://localhost:8000/redoc>
* OpenAPI：<http://localhost:8000/openapi.json>

手写补充（统一约定、业务语义、错误码、手搓示例）：[`docs/接口文档.md`](./docs/接口文档.md)

共 **36 个接口**：认证 2、工单 7、质量 8、看板 9、库存 5、报表 2、基础数据 2、健康检查 1（含）。

---

## 九、演示数据

```bash
bash scripts/seed.sh           # 幂等播种
bash scripts/seed.sh --reset   # 删库重建后全量播种
bash scripts/seed.sh --gateway 30   # 额外采集 30 帧设备数据
```

播种内容（随机种子固定为 `20260301`，**结果可复现**）：

* 主数据：车间、产线、设备、员工、班次、产品、BOM、工艺路线、物料、仓库、供应商；
* 业务数据：近 30 天的 **18 张工单**、**124 条报工记录**、**156 个 SPC 子组**、**6 张质检单**；
* 3 个演示账号：`admin` / `leader` / `worker`（口令 `mes@2026`）。

---

## 十、文档索引

| 文档 | 内容 |
| --- | --- |
| [`docs/数据库设计.md`](./docs/数据库设计.md) | 31 张表的字段级设计（由 ORM 元数据自动生成） |
| [`docs/接口文档.md`](./docs/接口文档.md) | 统一约定、错误码、36 个接口、手搓示例 |
| [`docs/部署文档.md`](./docs/部署文档.md) | 三种部署形态、环境变量、验证清单、常见问题 |
| [`docs/用户操作手册.md`](./docs/用户操作手册.md) | 九个界面的操作指引与 5 分钟演示路线 |

---

## 许可

[Apache License 2.0](./LICENSE)
