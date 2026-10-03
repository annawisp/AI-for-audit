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

TASK-101 建立工程边界；TASK-102 补充项目、文件、数据库和本地存储；TASK-202 在这些基础上落地统一 Evidence Object；TASK-203 补充字段标准化和数据集质量分级；TASK-301 建立文档与表格解析底座；TASK-302 从解析 chunks 中提取合同关键要素并生成 Evidence Object；TASK-303 基于合同提取 Evidence 执行规则版收入确认分析；TASK-304 基于合同、收入确认分析和可选收入记录识别收入风险信号；TASK-305 在相关数据存在时执行收入、应收、回款等核对和异常筛选；TASK-401 建立审计程序注册表，解释程序输入、依赖、输出和 readiness。

## 2. 各目录的责任

- `api`：接收和校验 HTTP 请求，不承载审计判断。
- `services`：组织用例，协调领域能力和存储。
- `orchestrator`：管理 Procedure 的注册、依赖、readiness 解释，后续扩展九态状态和局部失败。
- `capabilities`：文档解析、合同字段提取、收入确认、风险识别和数据核对等可独立运行的能力。
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

## 7. TASK-301 至 TASK-305 Capability 边界

TASK-301 到 TASK-305 负责提供收入循环审计程序可调用的基础能力，但不直接承担完整 Procedure Orchestrator 职责。

- TASK-301：把上传文件解析为可追溯 document chunks。
- TASK-302：从解析 chunks 中抽取合同要素，并生成 `capability:contract_extraction` Evidence。
- TASK-303：基于合同抽取 Evidence 执行规则版收入确认分析，并生成 `capability:revenue_recognition_analysis` Evidence。
- TASK-304：基于合同、收入确认分析和可选收入明细识别收入风险信号，并生成 `capability:revenue_risk_identification` Evidence。
- TASK-305：在相关资料存在时执行合同、收入、应收、回款等数据核对和异常筛选，并生成 `capability:data_reconciliation_anomaly_detection` Evidence。
- 以上 Capability 产生的是结构化能力结果或风险信号，不等同于正式审计结论；正式结论仍需后续状态机、人工复核和底稿机制支持。

## 8. TASK-401 Procedure Registry 边界

TASK-401 把收入循环审计程序的输入、依赖、输出和执行策略显式配置化。它不直接执行 Capability，也不提前实现 TASK-402 的九态状态机。

- `procedure_registry.json`：配置 P-REV-001 到 P-REV-005 五个程序定义，新增或调整程序依赖时不需要改核心加载代码。
- `procedure_registry`：加载配置并执行注册表质量校验。
- `required_inputs`：缺失时程序 readiness 为 `BLOCKED`。
- `optional_inputs`：缺失时可按程序 policy 进入 `READY` 或 `PARTIAL`。
- `dependent_inputs`：只影响依赖该输入的分析范围，不阻断全部程序。
- `upstream_dependencies`：记录程序依赖的前序程序，例如合同抽取依赖文档解析。
- `execution_policy`：描述 readiness 策略、是否允许部分执行、是否至少需要一类相关输入。
- `ProcedureRegistryConfigError`：对重复 `procedure_id`、非法 readiness 策略、未知 Capability、未知上游 Procedure 和非法 minimum input group 给出受控错误。
- `readiness` API：解释某程序为何 `READY`、`PARTIAL`、`BLOCKED` 或 `NOT_APPLICABLE`。