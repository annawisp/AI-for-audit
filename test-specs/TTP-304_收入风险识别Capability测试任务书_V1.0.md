# TTP-304 收入风险识别 Capability 测试任务书 V1.0

## 1. 测试对象

- 任务编号：TASK-304
- 能力名称：收入风险识别 Capability
- 仓库：annawisp/AI-for-audit
- 测试范围：后端能力函数、API 路由、证据落库、列表查询、异常处理、CI 基础质量门禁。

## 2. 验收目标

TASK-304 应在 TASK-302 合同抽取证据、TASK-303 收入确认分析证据及可选收入明细记录基础上，形成规则型收入风险识别结果，并将结果作为审计证据保存。当前阶段不要求接入真实 LLM 或外部服务，语义判断字段应明确标记为未启用或不可用。

## 3. 验收标准

1. 提供 `/api/v1/projects/{project_id}/revenue-risk` POST 接口，能够生成收入风险识别结果。
2. 提供同路径 GET 接口，能够返回项目下已生成的收入风险识别结果。
3. 支持合同证据、收入确认证据、收入明细记录三类输入覆盖率标识。
4. 对多履约义务、验收/截止、收入明细缺失或不完整等情形输出风险信号。
5. 生成 `capability:revenue_risk_identification` 来源的 evidence，保留结论、覆盖率、风险信号、限制事项和来源证据 ID。
6. 对错误证据来源返回 400，并给出稳定错误码。
7. 不破坏 TASK-101 至 TASK-303 既有接口和测试。

## 4. 自动化测试用例

| 用例编号 | 场景 | 期望结果 |
| --- | --- | --- |
| TTP-304-001 | 合同证据包含多履约义务及验收条件 | 返回 `REQUIRES_REVIEW`，整体风险为 `HIGH`，包含 `multiple_obligation_allocation` 风险信号 |
| TTP-304-002 | 仅提供完整收入明细记录 | 返回 201，收入明细覆盖率为 true，落库 evidence 来源为 `capability:revenue_risk_identification` |
| TTP-304-003 | `contract_evidence_id` 指向错误来源 evidence | 返回 400，错误码为 `invalid_contract_evidence_source` |
| TTP-304-004 | GET 查询收入风险结果 | 返回已生成结果列表，total 与结果数量一致 |
| TTP-304-005 | 远端 Foundation CI | ruff 与 pytest 通过 |

## 5. 执行命令

```bash
cd backend
ruff check app tests
pytest tests/test_task304_revenue_risk.py -q
pytest tests -q
```

## 6. 通过/失败判定

- 全部自动化测试通过，且 Foundation CI 通过：TASK-304 可进入后续搭建。
- 若仅因冷启动环境、GitHub Actions 外部环境或历史非 304 问题失败，应在测试报告中单独标记，不直接判定 TASK-304 功能失败。
- 若 TASK-304 新增接口、证据落库或风险信号断言失败，应判定 TASK-304 未通过，需要修复后重测。

## 7. 本轮测试记录

本任务书随 TASK-304 代码一起进入仓库 `test-specs/`。本轮远端 CI 结果以 GitHub Actions 最新 run 为准。
