from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ExtractionStatus = Literal["COMPLETED", "PARTIAL", "BLOCKED", "ABSTAINED", "REQUIRES_REVIEW"]
FieldStatus = Literal[
    "EXTRACTED",
    "ABSTAINED",
    "MISSING_IN_DOCUMENT",
    "NOT_APPLICABLE",
    "CONFLICTING_EVIDENCE",
]
ExtractorType = Literal["rule_based", "llm"]
ConfidenceLevel = Literal["low", "medium", "high"]


class ContractExtractionRequest(BaseModel):
    extractor_type: ExtractorType = "rule_based"


class SourceLocation(BaseModel):
    chunk_id: str | None = None
    source_locator: str | None = None
    page_number: int | None = None
    paragraph_number: int | None = None
    row_number: int | None = None
    sheet_name: str | None = None
    text_excerpt: str | None = None


class ContractFieldExtraction(BaseModel):
    field_name: str
    display_name: str
    status: FieldStatus
    value: Any = None
    source: SourceLocation | None = None
    sources: list[SourceLocation] = Field(default_factory=list)
    confidence_level: ConfidenceLevel | None = None
    confidence_basis: str | None = None
    extraction_reason: str | None = None
    extraction_method: str | None = None
    abstention_reason: str | None = None


class ContractExtractionResponse(BaseModel):
    extraction_run_id: str
    project_id: str
    document_id: str
    evidence_id: str | None
    status: ExtractionStatus
    extractor_type: ExtractorType
    extractor_version: str
    fields: list[ContractFieldExtraction]
    failure_reason: str | None
    created_at: datetime
    trace_id: str


class ContractExtractionListResponse(BaseModel):
    items: list[ContractExtractionResponse]
    total: int
