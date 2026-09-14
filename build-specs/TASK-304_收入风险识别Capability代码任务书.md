# TASK-304 收入风险识别 Capability 代码任务书 V1.0

## 一、任务定位

TASK-304 是收入循环智能审计助手中的独立能力模块：**收入风险识别 Capability**。

它的职责是基于已有证据和可选数据，识别收入相关风险信号，并输出结构化、可追溯、可复核的风险判断建议。

TASK-304 输出的是：

> 风险信号与风险判断建议，不是最终审计意见。

开发团队不得把 TASK-304 的结果直接等同于审计结论。最终结论仍需进入 Human Review。

## 二、当前仓库前置能力

开发前需先浏览当前 GitHub 仓库结构，重点确认以下模块已存在：

| 前置任务 | 当前作用 | TASK-304 如何使用 |
|---|---|---|
| TASK-202 | Evidence Object | TASK-304 输出统一 Evidence |
| TASK-203 | Normalization | 后续金额、日期标准化可复用 |
| TASK-301 | Document Processor | 已将文档解析为 chunks |
| TASK-302 | Contract Extraction | 提供合同要素 Evidence |
| TASK-303 | Revenue Recognition Analysis | 提供收入确认分析 Evidence |

TASK-304 应优先读取：

```text
source = capability:contract_extraction
source = capability:revenue_recognition_analysis
```

不应重新解析原始合同文件。

## 三、任务目标

TASK-304 需要达到以下目标：

1. 可独立调用、独立测试。
2. 不依赖完整 Agent 串行流程。
3. 可基于合同要素、TASK-303 收入确认分析、Project Context、可选收入记录运行。
4. 不强制要求 TASK-305 数据核对完成。
5. 采用 `Rules + LLM Judgment` 双轨结构。
6. 当前 MVP 可以不真实调用 LLM，但必须预留语义判断字段。
7. 生成统一 Evidence Object。
8. 输出 Coverage Ratio。
9. 无法计算的风险不得当作低风险。
10. 仅合同场景也能输出合同相关风险。

## 四、非目标

| 不做内容 | 原因 |
|---|---|
| 不做完整数据核对 | 留给 TASK-305 |
| 不做银行流水、应收、发票全链路匹配 | 留给后续数据核对任务 |
| 不输出正式审计结论 | 需要 Human Review |
| 不强制调用 LLM | MVP 可先保留接口 |
| 不做底稿生成 | 留给后续 Working Paper 任务 |
| 不重新解析合同原文 | 应复用 TASK-302/303 Evidence |

## 五、能力边界

TASK-304 应作为独立 Capability 实现，不依赖完整 Agent 串行流程。

验收标准：

- 可单独调用、单独测试。
- 不要求 TASK-305 数据核对已完成。
- 不要求收入明细、应收、银行流水全部存在。
- 缺失资料只影响依赖该资料的风险信号，不导致整体失败。
- 系统错误不得包装成审计风险结论。
- 风险结果必须进入 Evidence Object，不作为最终审计意见。

## 六、建议新增文件

建议新增：

```text
backend/app/capabilities/revenue_risk.py
backend/app/schemas/revenue_risk.py
backend/app/api/routes/revenue_risk.py
backend/tests/test_task304_revenue_risk.py
```

需要合并修改：

```text
backend/app/api/router.py
backend/app/core/database.py
backend/app/services/repository.py
README.md
docs/architecture.md
```

## 七、API 设计

建议新增接口：

```text
POST /api/v1/projects/{project_id}/revenue-risk
GET  /api/v1/projects/{project_id}/revenue-risk
```

### POST 请求示例

```json
{
  "contract_evidence_id": "xxx",
  "revenue_recognition_evidence_id": "xxx",
  "engine_type": "rule_based",
  "enable_semantic_judgment": false,
  "revenue_records": [
    {
      "record_id": "REV-001",
      "contract_reference": "HT-001",
      "recognition_date": "2026-03-31",
      "amount": "100000",
      "description": "Q1 software subscription revenue"
    }
  ]
}
```

### 请求字段要求

| 字段 | 是否必填 | 说明 |
|---|---|---|
| `contract_evidence_id` | 否 | 有合同层风险判断时使用 |
| `revenue_recognition_evidence_id` | 否 | 有 TASK-303 结果时使用 |
| `engine_type` | 是 | 当前支持 `rule_based` |
| `enable_semantic_judgment` | 否 | 当前默认 `false` |
| `revenue_records` | 否 | 可选收入记录 |

至少需要合同 Evidence 或 TASK-303 Evidence 之一，否则返回 `INSUFFICIENT_DATA`，不得抛 500。

## 八、核心 Schema 要求

### 风险状态

建议定义：

```python
RiskSignalStatus = Literal[
    "COMPLETE",
    "PARTIAL",
    "INSUFFICIENT_DATA",
    "NOT_APPLICABLE",
    "REQUIRES_REVIEW",
    "CONFLICTING_EVIDENCE",
]
```

含义：

| 状态 | 含义 |
|---|---|
| `COMPLETE` | 风险信号已完成判断 |
| `PARTIAL` | 部分数据可判断，但结论受限 |
| `INSUFFICIENT_DATA` | 缺少必要资料，无法判断 |
| `NOT_APPLICABLE` | 当前业务场景不适用 |
| `REQUIRES_REVIEW` | 需要人工复核 |
| `CONFLICTING_EVIDENCE` | 证据冲突 |

### 风险等级

```python
Severity = Literal["low", "medium", "high"]
```

### 来源类型

```python
SourceType = Literal["rule", "semantic_judgment", "llm_placeholder"]
```

### 单个风险信号结构

每个 risk signal 至少包含：

```json
{
  "risk_signal_id": "contract_amount_missing",
  "risk_name": "合同金额缺失或不明确",
  "risk_category": "contract_terms",
  "status": "COMPLETE",
  "severity": "medium",
  "source_type": "rule",
  "engine_type": "rule_based",
  "trigger_condition": "Contract amount field is missing or conflicting.",
  "basis": "transaction_price field was missing in TASK-302 evidence.",
  "evidence_references": ["contract_evidence_id"],
  "requires_review": true,
  "review_reason": "contract_amount_missing",
  "recommendation": "补充合同金额条款或人工复核交易价格。"
}
```

### 整体输出结构

整体输出至少包含：

```json
{
  "risk_run_id": "xxx",
  "project_id": "xxx",
  "source_evidence_ids": ["xxx", "xxx"],
  "status": "PARTIAL",
  "overall_risk_level": "medium",
  "coverage_ratio": 0.6,
  "rule_coverage_ratio": 0.6,
  "semantic_judgment_coverage": "not_enabled",
  "risk_signals": [],
  "limitations": [],
  "requires_review": true,
  "evidence_id": "xxx",
  "trace_id": "xxx"
}
```

## 九、数据库设计

建议新增表：

```sql
CREATE TABLE IF NOT EXISTS revenue_risk_runs (
    risk_run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    contract_evidence_id TEXT,
    revenue_recognition_evidence_id TEXT,
    evidence_id TEXT,
    status TEXT NOT NULL,
    overall_risk_level TEXT NOT NULL,
    coverage_json TEXT NOT NULL,
    risk_signals_json TEXT NOT NULL,
    limitations_json TEXT NOT NULL,
    source_evidence_ids_json TEXT NOT NULL,
    rule_coverage_ratio REAL,
    semantic_judgment_coverage TEXT NOT NULL,
    engine_type TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    llm_judgment_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (contract_evidence_id) REFERENCES evidence(evidence_id),
    FOREIGN KEY (revenue_recognition_evidence_id) REFERENCES evidence(evidence_id),
    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
);
```

## 十、规则库要求

第一版至少实现以下 10 个风险信号。

| risk_signal_id | 风险信号 | 所需输入 | 缺资料状态 |
|---|---|---|---|
| `contract_amount_missing_or_unclear` | 合同金额缺失或不明确 | TASK-302 `transaction_price` | `INSUFFICIENT_DATA` |
| `price_obligation_mismatch` | 交易价格与履约义务不匹配 | 履约义务、交易价格 | `PARTIAL` |
| `abnormal_payment_terms` | 收款条件异常 | 付款条件 | `INSUFFICIENT_DATA` |
| `acceptance_affects_recognition` | 验收条件影响收入确认 | 验收条款、TASK-303 | `INSUFFICIENT_DATA` |
| `special_terms_affect_recognition` | 特殊条款可能影响收入确认 | 特殊条款 | `INSUFFICIENT_DATA` |
| `unclear_revenue_timing` | 收入确认时点不清晰 | TASK-303 timing node | `INSUFFICIENT_DATA` |
| `revenue_records_missing` | 收入记录缺失导致金额层面无法测试 | revenue_records | `INSUFFICIENT_DATA` |
| `revenue_record_fields_incomplete` | 收入记录字段不完整 | revenue_records | `PARTIAL` |
| `revenue_date_outside_audit_period` | 收入记录日期超出审计期间 | revenue_records + Project Context | `INSUFFICIENT_DATA` |
| `revenue_amount_missing_or_abnormal` | 收入记录金额异常或缺失 | revenue_records | `PARTIAL` |

注意：无法计算的信号不得输出为 `COMPLETE` 或低风险。

## 十一、规则判断建议

### 1. 合同金额缺失或不明确

触发条件：

- TASK-302 中 `transaction_price` 缺失；
- 或 `transaction_price` 为 `CONFLICTING_EVIDENCE`；
- 或金额字段存在但无法标准化。

建议输出：

- 缺失：`INSUFFICIENT_DATA`
- 冲突：`CONFLICTING_EVIDENCE`
- 无法标准化：`PARTIAL`

### 2. 交易价格与履约义务不匹配

触发条件：

- 多个履约义务但没有分摊依据；
- TASK-303 中履约义务节点为 `REQUIRES_REVIEW`；
- 存在交易价格但无法对应各履约义务。

建议输出：

- `REQUIRES_REVIEW`
- severity: `medium` 或 `high`

### 3. 收款条件异常

触发条件：

- 付款条件明显早于交付或验收；
- 大额预收但缺少履约进度依据；
- 仅以付款节点作为收入确认依据。

建议输出：

- 可判断：`COMPLETE` 或 `REQUIRES_REVIEW`
- 缺少付款条件：`INSUFFICIENT_DATA`

### 4. 验收条件影响收入确认

触发条件：

- TASK-303 acceptance node 为 `REQUIRES_REVIEW`；
- 合同条款显示客户验收、上线确认、交付确认影响收入确认。

建议输出：

- `REQUIRES_REVIEW`
- severity: `medium` 或 `high`

### 5. 特殊条款可能影响收入确认

触发条件：

- 特殊条款包含退款、退货、质保、违约、折扣、返利、可变对价等。

建议输出：

- `REQUIRES_REVIEW`
- severity: `high`

### 6. 收入确认时点不清晰

触发条件：

- TASK-303 timing node 为 `PARTIAL` 或 `REQUIRES_REVIEW`；
- 无法区分某一时点确认还是某一期间确认。

建议输出：

- `REQUIRES_REVIEW`

### 7. 收入记录缺失

触发条件：

- `revenue_records` 为空或未提供。

建议输出：

- `INSUFFICIENT_DATA`
- 不得整体失败；
- 合同类风险继续执行。

### 8. 收入记录字段不完整

触发条件：

- 收入记录缺少 `recognition_date`；
- 缺少 `amount`；
- 缺少 `contract_reference`。

建议输出：

- `PARTIAL`
- 列出缺失字段和记录 ID。

### 9. 收入记录日期超出审计期间

触发条件：

- `recognition_date < audit_period_start`
- 或 `recognition_date > audit_period_end`

建议输出：

- `COMPLETE`
- severity: `high`
- requires_review: `true`

如果缺少审计期间：

- `INSUFFICIENT_DATA`

### 10. 收入记录金额异常或缺失

触发条件：

- 金额为空；
- 金额小于或等于 0；
- 金额无法解析；
- 单笔金额明显异常，第一版可采用简单阈值或只标记为需后续增强。

建议输出：

- 缺失或无法解析：`PARTIAL`
- 负数或 0：`REQUIRES_REVIEW`

## 十二、Coverage Ratio

必须输出：

```json
{
  "total_signals": 10,
  "assessable_signals": 6,
  "insufficient_data_signals": 3,
  "not_applicable_signals": 1,
  "coverage_ratio": 0.6667
}
```

建议公式：

```text
coverage_ratio = assessable_signals / (total_signals - not_applicable_signals)
```

其中以下状态计入 `assessable_signals`：

```text
COMPLETE
PARTIAL
REQUIRES_REVIEW
CONFLICTING_EVIDENCE
```

以下状态不计入风险评分分母：

```text
INSUFFICIENT_DATA
NOT_APPLICABLE
```

但必须进入 Coverage 和 Limitations 说明。

## 十三、风险评分要求

风险总评分只基于可评估信号，不把无法计算的信号当作 0 分。

建议：

| severity | 分值 |
|---|---|
| low | 1 |
| medium | 2 |
| high | 3 |

只对以下状态进入风险评分：

- `COMPLETE`
- `PARTIAL`
- `REQUIRES_REVIEW`
- `CONFLICTING_EVIDENCE`

不进入风险评分：

- `INSUFFICIENT_DATA`
- `NOT_APPLICABLE`

整体风险等级建议：

| 条件 | overall_risk_level |
|---|---|
| 存在 high 且 triggered=true | `high` |
| 存在 medium 或多个 review 信号 | `medium` |
| 仅低风险且覆盖充分 | `low` |
| 覆盖率过低 | `unknown` 或 `medium`，并进入 limitations |

## 十四、Rules + LLM 双轨处理

当前 MVP 建议：

| 类型 | 是否真实执行 | 处理方式 |
|---|---|---|
| Rules | 执行 | 完成高频结构化风险判断 |
| LLM Judgment | 暂不执行 | 预留字段，不伪造判断 |
| Semantic Judgment | 占位 | 标记 `not_enabled` 或 `requires_review` |

输出中必须区分：

```json
{
  "source_type": "rule",
  "engine_type": "rule_based"
}
```

或：

```json
{
  "source_type": "llm_placeholder",
  "engine_type": "semantic_judgment",
  "status": "REQUIRES_REVIEW",
  "basis": "Semantic judgment is not enabled in MVP."
}
```

LLM 不得覆盖规则事实。比如规则判断收入日期超出审计期间，LLM 不能把该事实改成无风险，只能补充解释或建议复核。

## 十五、语义判断占位要求

即使当前不接入真实 LLM，也需要保留以下字段：

- `judgment_type`
- `source_type`
- `engine_type`
- `llm_judgment_status`
- `semantic_judgment_coverage`

建议值：

```json
{
  "llm_judgment_status": "not_enabled",
  "semantic_judgment_coverage": "placeholder_not_enabled"
}
```

不得伪造模型判断结果。

## 十六、Evidence Object 要求

TASK-304 必须生成 Evidence Object。

字段建议：

```python
source = "capability:revenue_risk_identification"
execution_status = "completed"
node_status = "ready" | "partial" | "blocked"
judgment_status = "AI_GENERATED" | "PENDING_REVIEW" | "NEED_MORE_EVIDENCE"
confidence_level = "low" | "medium" | "high"
confidence_basis = "Rule-based revenue risk identification from TASK-302/TASK-303 evidence."
```

判断逻辑：

| 场景 | judgment_status |
|---|---|
| 存在 high 风险 | `PENDING_REVIEW` |
| 存在 `REQUIRES_REVIEW` | `PENDING_REVIEW` |
| 大量 `INSUFFICIENT_DATA` | `NEED_MORE_EVIDENCE` |
| 全部低风险且覆盖充分 | `AI_GENERATED` |

`extracted_value` 中必须包含：

```json
{
  "capability": "revenue_risk_identification",
  "risk_signals": [],
  "coverage": {},
  "limitations": [],
  "overall_risk_level": "medium",
  "requires_review": true
}
```

## 十七、人工复核要求

风险识别结果应支持人工复核。

验收标准：

1. 每个风险信号可独立标记 `requires_review`。
2. 高风险信号应默认进入人工复核。
3. 语义判断类风险应进入人工复核或至少标记为 AI judgment。
4. 输出应保留 `review_reason`。
5. 不得把复杂商业实质判断直接标为最终确认。

## 十八、异常与部分输入处理

| 场景 | 处理要求 |
|---|---|
| 缺少合同要素 | 合同类风险信号标记为 `INSUFFICIENT_DATA` |
| 缺少 TASK-303 结果 | 收入确认分析相关风险标记为 `INSUFFICIENT_DATA`，其他可评估信号继续执行 |
| 缺少收入记录 | 金额、截止、趋势类风险标记为 `INSUFFICIENT_DATA` |
| 收入记录字段不足 | 相关风险标记为 `PARTIAL` |
| 证据冲突 | 相关风险标记为 `CONFLICTING_EVIDENCE` 或 `REQUIRES_REVIEW` |
| 系统错误 | 不得包装成审计风险结论 |

## 十九、自动化测试要求

至少新增以下测试：

1. 仅合同输入，可输出合同相关风险。
2. 缺少收入记录，不整体失败。
3. 合同存在特殊条款，触发高风险或需复核。
4. 合同验收条款影响收入确认，触发风险信号。
5. 收入确认时点不清晰，触发 `REQUIRES_REVIEW`。
6. 收入记录存在但字段不完整，相关风险 `PARTIAL`。
7. 收入记录日期超出审计期间，触发截止性风险。
8. 无法计算信号不进入风险评分分母。
9. Coverage Ratio 正确。
10. Evidence Object Schema 正确。
11. 错误 Evidence source 被拒绝或标记为不可用。
12. `engine_type=llm` 当前不可用时返回明确错误，不得 500。
13. 规则信号与语义判断占位信号能够区分。
14. `rule_coverage_ratio` 与 `semantic_judgment_coverage` 分开输出。

验收命令：

```bash
cd backend
ruff check app tests
pytest tests
```

## 二十、最终交付物

开发团队最终应交付：

```text
TASK-304-only 代码压缩包
```

包内建议结构：

```text
repo-files/
  backend/app/api/routes/revenue_risk.py
  backend/app/capabilities/revenue_risk.py
  backend/app/schemas/revenue_risk.py
  backend/tests/test_task304_revenue_risk.py

integration-notes/
  router_task304_snippet.py
  database_task304_table.sql
  repository_task304_snippet.py
  shared_docs_task304_notes.md

README_TASK304_PACKAGE.md
```

不得包含：

```text
.venv/
node_modules/
dist/
__pycache__/
.pytest_cache/
.ruff_cache/
```

也不要把 TASK-201/202/203/301/302/303 的完整源码重复打入包中，除非是必须合并的共享文件片段。

## 二十一、开发团队开始前检查清单

开发团队正式写代码前，应先完成：

1. 浏览当前 GitHub 仓库目录结构。
2. 确认 TASK-302 的 `contract_extraction` Evidence 输出结构。
3. 确认 TASK-303 的 `revenue_recognition_analysis` Evidence 输出结构。
4. 确认 Evidence Object 创建 API 和 repository 写法。
5. 确认数据库初始化方式。
6. 确认现有测试风格。
7. 确认 TASK-304 不覆盖前序任务文件。
8. 确认新增共享文件修改以 patch/snippet 方式交付。

## 二十二、验收标准汇总

TASK-304 完成后应满足：

- 可独立调用。
- 可独立测试。
- 合同场景可运行。
- 缺收入记录不整体失败。
- 10 个高频风险信号进入规则库。
- 每个风险信号有唯一 `risk_signal_id`。
- 每个风险信号有状态、等级、依据、建议和复核标记。
- 无法计算的风险不进入评分分母。
- 输出 `coverage_ratio`。
- 输出 `rule_coverage_ratio`。
- 输出 `semantic_judgment_coverage`。
- 规则判断和语义判断来源分开。
- MVP 不伪造 LLM 判断。
- 结果生成 Evidence Object。
- 高风险或需复核事项进入 `PENDING_REVIEW`。
- Foundation CI 通过。
