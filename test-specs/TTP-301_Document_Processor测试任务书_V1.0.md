# TTP-301 Document Processor 测试任务书 V1.0

## 1. 测试目标

验证 TASK-301 文档与表格解析能力是否满足智能审计助手后续证据抽取、字段标准化和审计程序执行的基础要求。测试重点不是模型判断，而是稳定、可追溯、可复现地把已上传文件解析为结构化 chunk。

## 2. 验收范围

本任务覆盖以下能力：

- 支持已上传文档的解析入口：`POST /api/v1/projects/{project_id}/documents/{document_id}/parse`。
- 支持解析运行记录查询：`GET /api/v1/projects/{project_id}/documents/{document_id}/parse-runs`。
- 支持 chunk 查询：`GET /api/v1/projects/{project_id}/documents/{document_id}/chunks`。
- 对 TXT、CSV、DOCX、XLSX、PDF 文本层进行可追溯解析。
- 对扫描 PDF 返回 OCR_REQUIRED，并明确 OCR 当前不可用。
- 对空内容、表头但无数据、坏 DOCX/XLSX、未支持文件类型给出受控状态，不生成虚假 chunk。

## 3. 验收标准

### 3.1 解析成功类

1. TXT 文件应按非空行生成 paragraph chunk，保留 `sequence_number` 和 `source_locator`。
2. CSV 文件应按数据行生成 csv_row chunk，保留行号、字段名和原始行内容。
3. DOCX 文件应解析 paragraph/table row，保留段落号或表格行定位。
4. XLSX 文件应解析工作表行，保留 sheet name、row number 和 cell 值。
5. 带文本层 PDF 应生成 text chunk，保留 page locator。

### 3.2 边界状态类

1. 扫描型或无文本层 PDF 应返回 `OCR_REQUIRED`，`requires_ocr=true`，`ocr_status=NOT_AVAILABLE`。
2. 空 TXT 或仅表头 CSV 应返回 `ABSTAINED`，`failure_reason=no_parseable_content`，且 chunks_count 为 0。
3. 损坏或结构缺失的 DOCX/XLSX 应返回 `BLOCKED`，failure_reason 应包含具体解析失败类型。
4. 未支持文件类型应返回 `BLOCKED`，`failure_reason=unsupported_file_type`。

### 3.3 追溯性与数据完整性

1. 每个 chunk 必须包含 `chunk_id`、`parse_run_id`、`project_id`、`document_id`、`sequence_number`、`source_locator` 和 `created_at`。
2. 同一次 parse run 内 chunk 顺序应稳定，`sequence_number` 从 1 开始递增。
3. parse run 中 `chunks_count` 应与 chunk 查询结果数量一致。
4. 解析结果不得覆盖原始上传文件，不得修改原始 document metadata。

## 4. 自动化测试要求

在 GitHub Foundation CI 中至少执行：

- `ruff check app tests`
- `pytest -q`
- 前端静态构建/基础检查（沿用仓库 Foundation CI 配置）

新增测试文件建议放置于：

- `backend/tests/test_task301_document_parse.py`

## 5. 通过/失败判定

- 远端 Foundation CI 全部 job success：TASK-301 可标记为远端 CI 通过。
- 若仅因 OCR 真正识别能力不可用导致扫描 PDF 无法提取文本，不判定失败；MVP 阶段应以 `OCR_REQUIRED/NOT_AVAILABLE` 显式标记。
- 若出现未捕获异常、500 错误、虚假 chunk、chunk 缺少定位信息、或损坏文件被误判为成功，则判定失败。
