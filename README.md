# AI for Audit — 收入循环智能审计助手

这是收入循环智能审计助手的工程骨架。产品架构遵循：**Audit Procedure 是主流程，AI/Rules 是可插拔能力，Evidence 是统一输出，Human Review 是正式结论入口**。

当前完成范围：`Stage 1 / Step 1.2 / TASK-102`。

## 当前能力

- 前后端分离的项目结构
- FastAPI 后端和版本化 API 路由
- `/api/v1/health` 健康检查
- React + TypeScript 前端占位页
- pytest 单元测试框架
- 结构化日志和请求追踪基础件
- 环境变量模板与敏感信息隔离规则
- Python / Node 锁定依赖
- GitHub Actions 跨平台后端检查与前端构建配置
- SQLite 本地数据库初始化
- Project / Document 基础 API
- 脱敏样例文件上传与元数据登记
- 文件大小、类型和空文件校验

> 当前版本没有合同解析、审计程序状态机、AI 审计判断、Evidence 深度流转和真实客户资料处理。这些属于后续任务。
>
> 当前状态为 **TASK-102 本地整改完成后待验收**。健康检查通过只代表基础 API 服务可用，不代表收入审计智能体已经具备审计能力。

## 目录结构

```text
ai-for-audit/
├── backend/                # Python API 与审计能力后端
│   ├── app/
│   │   ├── api/            # HTTP API 路由
│   │   ├── capabilities/   # 独立审计能力模块
│   │   ├── core/           # 配置、日志等横切能力
│   │   ├── evidence/       # Evidence 组装（后续实现）
│   │   ├── models/         # 持久化模型（后续实现）
│   │   ├── orchestrator/   # Audit Procedure 编排器（后续实现）
│   │   ├── schemas/        # API / 领域数据结构
│   │   └── services/       # 应用服务
│   ├── tests/              # 后端自动化测试
│   └── requirements.lock   # Windows/Linux 通用锁定依赖
├── frontend/               # React 复核工作台前端
├── build-specs/            # 智能体搭建任务书（TASK）
├── test-specs/             # 测试任务书（TTP/TTEST/TTC）
├── docs/                   # 架构、决策与开发文档
├── knowledge_base/         # 脱敏知识样例与规则配置
├── logs/                   # 本地运行日志，不提交
├── sample_data/            # 仅允许脱敏/合成测试数据
├── templates/              # 底稿和导出模板
└── tests/                  # 跨模块与端到端测试
```

## 本地启动

### 1. 克隆并准备环境变量

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

macOS / Linux：

```bash
cp .env.example .env
```

`.env` 只用于本机，已被 `.gitignore` 排除。不要在其中放入客户资料。

### 2. 启动后端

项目支持 Python 3.11+；TASK-101 冷启动验收和 CI 使用 Python 3.12。

Windows PowerShell：

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.lock
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

macOS / Linux：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.lock
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000/api/v1/health>，应返回：

```json
{"status":"ok","service":"AI for Audit","version":"0.1.0","environment":"development"}
```

### 3. 运行后端测试

```bash
cd backend
ruff check .
pytest
```

测试配置会把警告视为失败，避免依赖弃用问题被静默忽略。

### 4. 启动前端

要求 Node.js 20.19+；推荐使用 Node.js 22 或 24。

```bash
cd frontend
npm ci
npm run dev
```

打开 <http://localhost:5173>。前端会读取 `VITE_API_BASE_URL` 并显示后端连接状态。

生产构建验证：

```bash
npm run build
```

后端关闭时刷新页面，应显示“后端未连接”；重新启动后端并再次刷新，应恢复为“后端已连接”。当前版本不承诺自动轮询恢复。

## 安全约束

- 禁止提交 API Key、密码、私钥、客户合同、收入明细、银行流水或未脱敏底稿。
- 真实资料不得进入当前 MVP 上传目录；当前上传接口仅用于脱敏样例文件验证。
- `sample_data` 只保存人工合成或充分脱敏的数据，并标明来源类型。
- 日志不得输出原始合同全文、身份证号、银行账号或完整交易明细。
- 提交前运行测试，并执行 `git status --short` 与 `git diff --staged`。
- `pytest` 会检查常见敏感文件、运行日志和构建产物是否被 Git 忽略，并扫描已跟踪文本中的明显密钥模式。

## TASK-102 本地验收命令

在完成依赖安装后执行：

```bash
cd backend
ruff check .
pytest
cd ../frontend
npm ci
npm run build
cd ..
git status --short
```

正式验收仍需基于上传到 GitHub 的候选 commit SHA 执行 GitHub Actions 和非开发人员 Windows 11 冷启动。

## 下一步

按任务书进入 `Stage 2 / Step 2.1 / TASK-201`：设计 Project Context MVP，明确项目级上下文的最小必要字段、版本记录和缺失资料处理方式。

架构说明见 [`docs/architecture.md`](docs/architecture.md)，关键技术决策见 [`docs/decisions/ADR-001-foundation-stack.md`](docs/decisions/ADR-001-foundation-stack.md)。
