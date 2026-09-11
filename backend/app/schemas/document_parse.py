from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ParseStatus = Literal[
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "PARTIAL",
    "BLOCKED",
    "ABSTAINED",
    "OCR_REQUIRED",
]
OcrStatus = Literal["NOT_REQUESTED", "REQUESTED", "NOT_AVAILABLE", "COMPLETED", "FAILED"]
ChunkType = Literal["text", "paragraph", "table_row", "spreadsheet_row", "csv_row"]


class DocumentParseRequest(BaseModel):
    allow_ocr_fallback: bool = False


class DocumentParseRunResponse(BaseModel):
    parse_run_id: str
    project_id: str
    document_id: str
    status: ParseStatus
    parser_name: str
    parser_version: str
    requires_ocr: bool
    ocr_requested: bool
    ocr_status: OcrStatus
    failure_reason: str | None
    chunks_count: int
    started_at: datetime
    completed_at: datetime | None
    trace_id: str


class DocumentParseRunListResponse(BaseModel):
    items: list[DocumentParseRunResponse]
    total: int


class DocumentChunkResponse(BaseModel):
    chunk_id: str
    parse_run_id: str
    project_id: str
    document_id: str
    chunk_type: ChunkType
    sequence_number: int = Field(ge=1)
    text: str
    content: Any = None
    page_number: int | None = Field(default=None, ge=1)
    sheet_name: str | None = None
    row_number: int | None = Field(default=None, ge=1)
    paragraph_number: int | None = Field(default=None, ge=1)
    table_index: int | None = Field(default=None, ge=1)
    source_locator: str
    created_at: datetime
    trace_id: str


class DocumentChunkListResponse(BaseModel):
    items: list[DocumentChunkResponse]
    total: int
