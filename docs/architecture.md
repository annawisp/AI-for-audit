# 工程架构说明

## 1. 为什么不是“多个 Agent 串行执行”

收入审计资料经常不完整，项目也不一定执行任务书中的全部程序。如果把系统做成固定串行 Agent，一处缺资料就容易阻断整条链路。工程结构因此围绕以下稳定对象组织：

```text
API → Application Service → Audit Procedure Orchestrator → Capability
                                           ↓                 ↓
                                      Execution State     Evidence
                                           ↓                 ↓
                                         Review → Working Paper
```

TASK-101 建立工程边界；TASK-102 补充项目、文件、数据库和本地存储；TASK-202 在这些基础上落地统一 Evidence Object；TASK-203 补充字段标准化和数据集质量分级。

## 2. 各目录的责任

- `api`：接收和校验 HTTP 请求，不承载审计判断。
- `services`：组织用例，协调领域能力和存储。
- `orchestrator`：后续管理 Procedure 的依赖、九态状态和局部失败。
- `capabilities`：合同解析、收入确认、风险识别等可独立运行的能力。
- `evidence`：负责统一证据对象、证据链和来源定位；TASK-202 先实现 Evidence Object Schema、状态流转和版本读取。
- `normalization`：负责原始值、标准值、转换规则和质量状态；TASK-203 先覆盖金额、日期、币种、数字和文本。
- `models`：后续存放数据库持久化模型。
- `schemas`：API 与领域对象的显式数据契约。
- `core`：配置、日志、安全和追踪等公共基础设施。

## 3. 关键约束

1. Capability 不直接决定某项审计程序是否执行，由 Orchestrator 管理。
2. Capability 不输出自由格式结论作为正式结果，后续必须转换为 Evidence Object。
3. 技术异常、资料缺失、业务不适用和人工未执行是不同语义，不共用一个失败状态。
4. 日志只记录定位和运行元数据，不记录客户资料正文。
5. 前端是结构化 Review Workbench 的载体，不把聊天框当作唯一产品界面。

## 4. 第一阶段接口

`GET /api/v1/health` 仅证明 API 进程及基础配置可用。它不代表数据库、模型服务、文件存储或审计能力健康；这些依赖加入后应扩展为分项 readiness 检查。

## 5. TASK-202 Evidence Object 边界

TASK-202 的 Evidence Object 是规则、AI 判断、人工复核和底稿输出共同使用的数据契约。当前只实现证据对象的结构化保存、读取、状态更新和历史版本快照，不实现合同解析、收入确认判断或底稿生成。

- `execution_status`：记录能力或程序执行层面的状态。
- `node_status`：记录该证据节点在流程中是否可用、部分可用或阻塞。
- `judgment_status`：记录审计判断和人工复核流转，覆盖 `AI_GENERATED`、`PENDING_REVIEW`、`CONFIRMED`、`MODIFIED`、`REJECTED`、`NEED_MORE_EVIDENCE`。

## 6. TASK-203 Normalization 边界

TASK-203 不解析合同、不生成审计结论，也不提前实现完整 Procedure Orchestrator。它只负责把能力模块或人工录入得到的结构化字段转换为可追溯的标准化记录，并对数据集可用性给出分级。

- `normalized_values`：保存 `raw_value`、`standard_value`、`normalization_rule`、`quality_status` 和问题列表。
- `dataset_quality_snapshots`：保存数据集记录数、质量分数和 `procedure_readiness`。
- `procedure_readiness`：为后续 Procedure 提供 `READY`、`PARTIAL`、`ABSTAINED` 输入，不在本任务中触发真实审计程序。
