# 工程架构说明（TASK-101）

## 1. 为什么不是“多个 Agent 串行执行”

收入审计资料经常不完整，项目也不一定执行任务书中的全部程序。如果把系统做成固定串行 Agent，一处缺资料就容易阻断整条链路。工程结构因此围绕以下稳定对象组织：

```text
API → Application Service → Audit Procedure Orchestrator → Capability
                                           ↓                 ↓
                                      Execution State     Evidence
                                           ↓                 ↓
                                         Review → Working Paper
```

TASK-101 只建立这些边界，不提前实现业务逻辑。

## 2. 各目录的责任

- `api`：接收和校验 HTTP 请求，不承载审计判断。
- `services`：组织用例，协调领域能力和存储。
- `orchestrator`：后续管理 Procedure 的依赖、九态状态和局部失败。
- `capabilities`：合同解析、收入确认、风险识别等可独立运行的能力。
- `evidence`：后续负责统一证据对象、证据链和来源定位。
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

