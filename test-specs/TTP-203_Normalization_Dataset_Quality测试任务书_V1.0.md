# TTP-203 数据标准化与质量分级测试任务书 V1.0

## 1. 测试对象

- 项目：AI for audit
- 任务：TASK-203 数据标准化与质量分级
- 测试范围：后端 Normalization API、标准化服务、SQLite 持久化、数据集质量分级、与 TASK-202 Evidence Object 的兼容关系

## 2. 验收目标

TASK-203 应在不生成审计结论、不提前实现完整 Procedure Orchestrator 的前提下，提供可追溯的数据标准化与质量分级能力：

1. 能保存原始值 `raw_value`、标准值 `standard_value`、标准化规则 `normalization_rule`、质量状态 `quality_status` 和问题列表 `issues`。
2. 能对金额、日期、币种、数字、文本字段执行基础标准化。
3. 无法解析的字段不得被静默丢弃，应返回 `partial` 状态和明确问题码。
4. 缺失字段应返回 `abstained` 状态。
5. 能保存数据集质量快照，并输出 `READY`、`PARTIAL`、`ABSTAINED` 的 procedure readiness 输入。
6. API 不得破坏 TASK-101/102/201/202 已有能力，包括项目、文档、Evidence、Project Context 和 CI。

## 3. 测试环境

- Python：3.12 或 CI 指定版本
- 后端依赖：`backend/requirements.lock`
- 前端依赖：`frontend/package-lock.json`
- 数据库：测试临时 SQLite 文件
- 测试数据：人工合成或脱敏样例，禁止真实客户资料

## 4. 自动化测试命令

在仓库根目录执行：

```bash
cd backend
ruff check .
pytest
cd ../frontend
npm ci
npm run build
```

如需单独执行 TASK-203 覆盖用例：

```bash
cd backend
pytest tests/test_task203_normalization.py
```

## 5. 功能测试用例

| 编号 | 测试项 | 操作 | 预期结果 |
|---|---|---|---|
| TTP-203-001 | 金额标准化 | 创建项目后调用 `POST /api/v1/projects/{project_id}/normalization/values`，提交 `raw_value=¥1,200.50`、`value_type=amount` | 返回 201；`standard_value=1200.50`；`normalization_rule=amount_decimal_v1`；`quality_status=ready`；`quality_score=100` |
| TTP-203-002 | 不可解析日期 | 提交 `raw_value=date pending manual review`、`value_type=date` | 返回 201；`standard_value=null`；`quality_status=partial`；`issues` 包含 `date_parse_failed` |
| TTP-203-003 | 英文日期标准化 | 提交 `raw_value=10 Sep 2026`、`value_type=date` | 返回 201；`standard_value=2026-09-10`；`quality_status=ready` |
| TTP-203-004 | 数据集部分可用 | 调用 `POST /api/v1/projects/{project_id}/normalization/datasets/quality`，提交 total=10、usable=3、partial=4、rejected=3、issues=`missing_invoice_dates` | 返回 201；`quality_score=50`；`quality_status=partial`；`procedure_readiness=PARTIAL` |
| TTP-203-005 | 空数据集 abstain | 提交 total=0、usable=0、partial=0、rejected=0 | 返回 201；`quality_score=0`；`quality_status=abstained`；`procedure_readiness=ABSTAINED`；`issues` 包含 `dataset_has_no_records` |
| TTP-203-006 | 查询标准化记录 | 创建标准化记录后调用 `GET /normalization/values` | 返回 200；`total` 正确；记录包含 raw/standard/rule/status/issues |
| TTP-203-007 | 查询数据集质量记录 | 创建数据集质量快照后调用 `GET /normalization/datasets/quality` | 返回 200；`total` 正确；记录包含质量分数和 readiness |
| TTP-203-008 | 关联对象校验 | 提交不存在的 `document_id`、`procedure_id` 或 `evidence_id` | 返回 400；错误码分别指向对应对象不存在 |
| TTP-203-009 | 旧能力回归 | 执行全部 pytest | TASK-101/102/201/202 既有用例仍通过 |

## 6. 非功能与安全测试

1. 不允许提交 `.env`、日志、数据库文件、上传目录、构建产物或真实客户资料。
2. 标准化记录必须保留原始值和规则名称，保证可追溯。
3. `partial` 和 `abstained` 应作为业务质量状态，不得被当作技术异常导致 API 500。
4. GitHub Actions 远程 CI 应通过。

## 7. 验收通过标准

满足以下条件可判定 TASK-203 代码验收通过：

- `ruff check .` 通过。
- `pytest` 通过，且 `tests/test_task203_normalization.py` 全部通过。
- 前端 `npm run build` 通过。
- GitHub Actions 远程 CI 通过。
- 未发现敏感信息、构建产物或本地运行文件被提交。

## 8. 已知限制

- TASK-203 不负责合同解析、审计判断、底稿生成和完整 Procedure Orchestrator。
- 当前标准化规则为 MVP 级别，复杂地区格式、行业字段和多语言规则后续任务扩展。
- `procedure_readiness` 仅为后续审计程序提供输入，不在本任务中触发真实审计程序。
