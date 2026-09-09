# TTP-202 Evidence Object Schema 测试任务书 V1.0

> 对应搭建任务：TASK-202 Evidence Object Schema  
> 所属阶段：Stage 2 审计数据与证据模型 / Step 2.2 建立统一 Evidence Object  
> 测试目的：验证规则、AI 判断、人工复核和底稿输出共同使用的统一 Evidence Object 是否可创建、校验、流转、转换和按版本追溯。

## 1. 测试目标

本测试任务书用于验证 TASK-202 是否实现统一 Evidence Object Schema，并确保后续合同解析、收入确认、风险识别、人工复核和底稿生成能够使用同一套证据对象。

重点验证：

- Evidence Object 字段完整性；
- 状态枚举合法性；
- `node_status` 与 `judgment_status` 独立维护；
- `model_confidence`、`confidence_level`、`confidence_basis` 等置信度字段完整；
- 能力模块核心结果可转换为统一 Evidence Object；
- 人工复核状态可按规则流转；
- 历史 Evidence Object 可按版本读取；
- 异常输入返回受控错误，不导致服务崩溃。

## 2. 测试范围

纳入测试：

- Evidence Object Schema / Model / Pydantic Schema；
- Evidence 创建、查询、列表、状态更新接口或服务；
- Evidence 版本管理逻辑；
- Judgment Status 流转逻辑；
- 能力模块输出到 Evidence Object 的 adapter / converter；
- Evidence 与 Project、Procedure、Document 的基础关联校验。

不纳入本轮测试：

- 合同解析准确率；
- LLM 判断准确率；
- 完整 Data Lineage 可视化；
- Review Workbench 前端完整交互；
- 底稿生成完整性。

上述内容分别属于 TASK-301、TASK-302、TASK-501、TASK-503、TASK-601 等后续测试范围。

## 3. 前置条件

- TASK-101 基础工程可运行；
- TASK-102 基础 API、数据库和文件存储可运行；
- TASK-201 Project Context MVP 已完成或不阻塞 Evidence 创建；
- 后端测试环境可执行 `pytest`；
- 测试数据库可初始化或使用隔离临时库；
- 不使用真实客户资料、API Key、密码或其他敏感信息。

## 4. 验收标准

| 编号 | 验收点 | 通过标准 |
|---|---|---|
| AC-202-01 | 统一 Evidence Object Schema | 系统存在统一 Evidence Object 数据结构，不允许能力模块输出互不兼容结构 |
| AC-202-02 | 必填字段完整 | 至少覆盖 `evidence_id`、`project_id`、`procedure_id`、`source`、`extracted_value`、`conclusion`、`execution_status`、`node_status`、`judgment_status`、`confidence`、`reviewer`、`timestamp` |
| AC-202-03 | 状态分离 | `node_status` 与 `judgment_status` 可独立维护 |
| AC-202-04 | 置信度结构完整 | 支持 `model_confidence`、`confidence_level`、`confidence_basis` |
| AC-202-05 | 能力模块结果可转换 | 合同提取、规则判断、AI 判断等核心结果可转换为 Evidence Object |
| AC-202-06 | Judgment 状态流转正确 | 支持并约束 `AI_GENERATED` / `PENDING_REVIEW` / `CONFIRMED` / `MODIFIED` / `REJECTED` / `NEED_MORE_EVIDENCE` |
| AC-202-07 | 历史版本可读取 | Evidence 修改后保留版本，可读取指定历史版本 |
| AC-202-08 | 异常受控 | 非法状态、非法置信度、无效关联等返回受控错误，不产生 500 或脏数据 |

## 5. 测试用例

| 用例编号 | 优先级 | 测试名称 | 测试动作 | 预期结果 |
|---|---|---|---|---|
| TTC-202-001 | P0 | 创建完整 Evidence Object | 使用完整字段创建 Evidence | 返回 201，字段完整保存 |
| TTC-202-002 | P0 | 缺少必填字段校验 | 缺少 `source` 或关键字段创建 Evidence | 返回 422 或受控校验错误 |
| TTC-202-003 | P0 | 非法状态校验 | 输入非法 `judgment_status` / `node_status` | 返回 422，不写入数据 |
| TTC-202-004 | P0 | 置信度边界校验 | 输入 `confidence > 1` 或 `< 0` | 返回 422 |
| TTC-202-005 | P0 | node_status 与 judgment_status 独立维护 | 设置节点已分析、判断待复核 | 两个状态可同时存在且不互相覆盖 |
| TTC-202-006 | P0 | AI 生成到待复核 | `AI_GENERATED -> PENDING_REVIEW` | 流转成功并新增版本 |
| TTC-202-007 | P0 | 人工确认 | `PENDING_REVIEW -> CONFIRMED`，提供 reviewer | 流转成功，记录 reviewer 和 timestamp |
| TTC-202-008 | P0 | 人工修改 | `PENDING_REVIEW -> MODIFIED`，提供 reviewer 和修改结论 | 流转成功，保留历史版本 |
| TTC-202-009 | P0 | 人工拒绝 | `PENDING_REVIEW -> REJECTED`，提供 reviewer | 流转成功，状态可查询 |
| TTC-202-010 | P0 | 需要更多证据 | `PENDING_REVIEW -> NEED_MORE_EVIDENCE` | 流转成功 |
| TTC-202-011 | P0 | 禁止最终状态非法回退 | `CONFIRMED -> AI_GENERATED` | 返回 400 `invalid_judgment_transition` 或等价受控错误 |
| TTC-202-012 | P0 | 最终复核状态必须有 reviewer | 不提供 reviewer 设置 `CONFIRMED/MODIFIED/REJECTED` | 返回 422 |
| TTC-202-013 | P1 | Procedure 关联校验 | 使用不存在的 `procedure_id` 创建 Evidence | 返回 400 `procedure_not_found` 或等价受控错误，不返回 500 |
| TTC-202-014 | P1 | Document 关联校验 | 使用不存在的 `document_id` 创建 Evidence | 返回受控错误 |
| TTC-202-015 | P1 | 按 Project 查询 Evidence | 两个项目分别创建/查询 Evidence | 只能查询到本项目 Evidence |
| TTC-202-016 | P1 | 历史版本读取 | 修改 Evidence 后读取 `/versions/1` | 返回第一版内容，当前版本与历史版本可区分 |
| TTC-202-017 | P1 | 合同提取结果转换 | 调用 contract extraction adapter | 输出符合 EvidenceCreate Schema |
| TTC-202-018 | P1 | 规则结果转换 | 调用 rule result adapter | 输出符合 EvidenceCreate Schema |
| TTC-202-019 | P1 | AI 判断结果转换 | 调用 AI judgment adapter | 输出符合 EvidenceCreate Schema |
| TTC-202-020 | P1 | 异常输入不导致服务崩溃 | 提交空 source、非法 confidence、无效关联 | 返回 4xx 受控错误，服务仍可继续处理请求 |

## 6. 自动化测试建议

建议至少包含以下测试文件或等价覆盖：

```text
backend/tests/test_task202_evidence.py
backend/tests/test_task202_evidence_schema.py
backend/tests/test_task202_evidence_status_flow.py
backend/tests/test_task202_evidence_versioning.py
backend/tests/test_task202_evidence_adapter.py
```

建议执行命令：

```bash
cd backend
ruff check .
pytest
pytest tests/test_task202_evidence.py
```

如本地测试副本不包含 `.git` 元数据，`test_repository_hygiene.py` 可能因无法执行 `git ls-files` 失败；该情况应作为测试环境限制单独标记，不应直接判定 TASK-202 功能失败。正式 GitHub Actions 环境应在真实 Git 仓库中运行。

## 7. 通过标准

TASK-202 判定通过需满足：

- Evidence Object 统一 Schema 存在；
- 核心字段完整并可读写；
- 非法字段、非法状态、非法置信度会被拒绝；
- `node_status` 与 `judgment_status` 可独立维护；
- Judgment 状态按规则流转，最终状态不能随意回退；
- 最终人工复核状态要求 reviewer；
- 能力模块输出可转换为 Evidence Object；
- Evidence 历史版本可读取；
- 关键异常返回受控错误，不导致服务崩溃；
- 本地自动化测试和 GitHub Actions 远程 CI 通过。

## 8. 不通过或部分通过情形

以下情况应判定为未通过或部分通过：

- 能力模块仍输出互不兼容结构；
- Evidence Object 缺少核心字段；
- `node_status` 与 `judgment_status` 被混为一个字段；
- 人工复核覆盖 AI 原判断，无法读取历史版本；
- 非法状态值可写入数据库；
- 无效 `procedure_id`、`document_id` 等关联导致 500；
- CI 或 TASK-202 自动化测试失败。
