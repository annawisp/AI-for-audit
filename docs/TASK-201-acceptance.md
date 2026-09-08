# TASK-201 开发交付自检记录

> 文档类型：**搭建任务开发自检记录，不是 TTP-201 最终测试结论**。正式测试任务、用例和签署要求以将来发布的 `test-specs/TTP-201_*.md` 为准。

- 验收日期：2026-09-07
- 任务：Stage 2 / Step 2.1 / TASK-201 Project Context MVP
- 结论：代码实现完成；本地自动化验证通过（ruff + pytest 19 passed，见 §6）。TTP-201 尚不可签署 PASS（需正式测试任务书与远端 CI/冷启动验收）

## 1. 产品边界

本任务建立"项目级最小必要信息"的统一上下文对象，作为 Stage 2 审计数据模型的第一步，证明"小数据也能启动、缺数据不阻塞"的产品原则可落地。

本次包含：

- 五段核心上下文 payload schema：基础信息 / 审计期间 / 重要性 / 收入模式 / 合同
- 版本化 JSON 快照持久化（`project_context_versions` 表），历史全保留
- 每次变更记录：版本号、变更人、变更原因、变更字段摘要
- 就绪评估接口：逐段 `provided / partial / not_provided` + 最小启动条件判断
- 合同两种登记形态：已上传文档引用、人工摘要（要素解析不在此任务）
- 版本 1 从项目主数据带出被审计单位与审计期间（避免重复录入）
- 相应后端单元测试（tests/test_task201_project_context.py）

本次不包含：

- Evidence Object Schema（TASK-202）
- 数据标准化与质量分级 raw/standard 值（TASK-203）
- 合同要素提取与收入判断能力（TASK-302 / TASK-303 / TASK-304）
- 程序九态状态机、依赖图与 Execution Manifest（Stage 4 / TASK-402）
- Data Lineage 六态（MISSING / NOT_PROVIDED / …，TASK-501 起）
- MVP 2.0 扩展段（收入明细 / 客户名单 / 供应商名单 / 应收账款 / 银行流水）
- 前端界面（Review Workbench 在 Stage 5）

## 2. 任务书逐项验收

### AC-201-01：只提供基础信息和合同时也能创建并启动项目

状态：实现完成，待自动化验证。

- 最小启动条件 = 基础信息段（被审计单位名称）已提供，接口：`GET .../context/readiness`
  - 无上下文时：返回 200，`minimal_requirements_met=false`，`context_version=null`，不报错
  - 仅基础信息时：`minimal_requirements_met=true`
  - 只给行业不给单位名称：状态 `partial`，缺 `entity_name`，不满足最小条件但不阻塞项目存在
- 仅合同（文档引用或人工摘要）也可随上下文提交；合同缺失本身不阻塞
- 项目创建（TASK-102 行为）不依赖上下文存在，本项目不改变该语义

### AC-201-02：缺少扩展数据不会阻塞全部程序

状态：实现完成，待自动化验证。

- 就绪报告显式区分：核心段（5 个）+ 扩展段（5 个，全部标注 `mvp_2_0_optional`、`not_provided`）
- `missing_does_not_block=true`：就绪评估只描述可用性，不把"未提供"解释为"程序未执行"；
  程序层 Abstention 语义由 Stage 4 编排器消费本报告实现
- 扩展数据即便缺失，项目创建、文档上传、上下文读写均不受影响（回归测试覆盖）

### AC-201-03：Project Context 版本变化可追踪

状态：实现完成，待自动化验证。

- 每次写入追加不可变版本：version 递增、历史行保留、`is_current` 标记最新
- 每次写入记录：changed_by / change_reason / changed_at / changed_sections（与上一版相比变更的核心段）
- 可读任意历史快照：`GET .../context/versions/{version}`
- 版本写入使用 `BEGIN IMMEDIATE` 串行化，保证同项目版本号不重复（UNIQUE(project_id, version)）
- 未来 MVP 2.0 扩 schema：JSON 快照方式天然兼容，旧版本永远按原样可读、可回放

## 3. 已确认设计决策

| # | 决策 | 选择 | 说明 |
| --- | --- | --- | --- |
| 1 | 合同形态 | 文档引用 + 人工摘要并存 | 引用为主、摘要为辅；合同要素解析明确留给 TASK-302 |
| 2 | 持久化方案 | 版本化 JSON 快照 | 与 evidence.payload_json 风格一致；1.0→2.0 扩字段免迁移 |
| 3 | "不阻塞"落地 | 就绪评估接口 | 供后续 Orchestrator 判断 READY/BLOCKED，本版只描述可用性 |
| 4 | 交付范围 | 代码+测试+README/docs 打包 zip，不自动 commit/push | 本地自检记录见本文档 §6 |

写入语义（重要）：**每次 POST 是完整快照替换**——客户端应提交当前完整五段内容；未提交的段视为"该版本未提供/清除"。版本历史保证可回退、可 diff。需要增量修改时，建议先 `GET .../context` 取当前 payload 作为基底再修改提交（先读后写）。

## 4. 接口与数据结构

### 接口

基础路径 `/api/v1/projects/{project_id}/context`：

| 方法 | 路径 | 成功 | 主要错误 |
| --- | --- | --- | --- |
| POST | `/context` | 201 新版本 | 404 project_not_found；400 document_not_in_project / duplicate_document_reference |
| GET | `/context` | 200 当前版本 | 404 context_not_found（尚未创建） |
| GET | `/context/versions` | 200 元数据清单 | 404 project_not_found |
| GET | `/context/versions/{version}` | 200 单版本快照 | 404 context_version_not_found |
| GET | `/context/readiness` | 200 就绪报告（无上下文也 200） | 404 project_not_found |

### 表

```sql
CREATE TABLE IF NOT EXISTS project_context_versions (
    version_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    changed_by TEXT,
    change_reason TEXT,
    changed_sections TEXT NOT NULL,   -- JSON array of core section names
    is_current INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    UNIQUE (project_id, version)
);
```

## 5. 测试设计（tests/test_task201_project_context.py）

| 用例 | 覆盖 |
| --- | --- |
| minimal_basic_info_creates_and_starts_project | AC-1：最小上下文 201、就绪报告、扩展段标注、summary |
| updates_append_traceable_snapshots | AC-3：v1→v2 变更段摘要、版本清单顺序/is_current、历史读取、版本不存在 404 |
| readiness_distinguishes_missing_and_partial | AC-2：无上下文 / partial（行业、无金额重要性）/ 全核心段 provided |
| version1_seeds_entity_and_period_from_project | 版本 1 主数据带出 entity_name + audit_period，changed_sections 正确 |
| contract_entries_support_documents_and_manual_summaries | 文档引用校验：跨项目/不存在→400、重复引用→400、手动摘要可用 |
| payload_validation_rejects_inconsistent_input | 422：期间倒置、合同缺 title 与 document_id、有效期倒置 |
| context_endpoints_return_structured_not_found | 404 错误码体系与现有项目/文档路由一致 |

## 6. 本地验证命令与结果

```bash
cd backend
ruff check .
pytest            # 全量：既有 TASK-101/102 用例 + 新增 TASK-201 用例
```

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 静态检查（ruff，行宽 100，E/F/I/B/UP） | `ruff check .` | 通过（All checks passed） |
| 后端全量测试（含 101/102 回归） | `pytest` | 通过（19 passed，警告视为失败配置下无告警） |

> 执行环境：Python 3.12 + 仓库锁定依赖 requirements.lock。19 项 = TASK-101/102 既有 12 项
> + TASK-201 新增 7 项。

## 7. 给产品经理的说明

1. **"只给基础信息也能启动"的口径**：最小条件只要求基础信息段存在被审计单位名称。重要性、
   收入模式等是"审计判断/业务信息"，缺失时系统不猜测、不阻塞，留待能力层 Abstention——这正是
   V1.3 §5.13"缺失资料 ≠ 审计师未执行程序"的落地形态。
2. **为什么合同用引用+摘要**：真实合同内容解析是 TASK-302；本任务先解决"知道哪些文档是合同、
   项目有哪些合同"的上下文问题，避免把解析语义提前固化。
3. **快照替换 vs 字段合并**：选择快照替换是因为审计变更必须可回放、可对账；代价是客户端增量
   更新需"先读后写"。若后续体验要求字段级 merge，可在不改表结构的前提下增加 PATCH 语义层。
4. **扩展数据何时进系统**：MVP 2.0 建议与 TASK-203 质量分级一起引入（客户名单/收入明细等需要
   raw/standard 规范化），避免现在存了将来还要清洗一遍。

## 8. 下一步

按任务书进入 `Stage 2 / Step 2.2 / TASK-202`：统一 Evidence Object Schema。建议先与业务确认
`node_status` / `judgment_status` 各自的合法取值集合与流转图（AI_GENERATED → PENDING_REVIEW →
CONFIRMED / MODIFIED / REJECTED / NEED_MORE_EVIDENCE），再定 JSON Schema 与表结构。
