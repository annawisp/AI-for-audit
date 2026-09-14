from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AnalysisStatus = Literal["COMPLETED", "PARTIAL", "BLOCKED", "ABSTAINED", "REQUIRES_REVIEW"]
AnalyzerType = Literal["rule_based", "llm"]
ConfidenceLevel = Literal["low", "medium", "high"]


class RevenueRecord(BaseModel):
    record_id: str | None = None
    recognition_date: str | None = None
    amount: Any = None
    contract_reference: str | None = None
    description: str | None = None


class RevenueRecognitionRequest(BaseModel):
    contract_evidence_id: str
    analyzer_type: AnalyzerType = "rule_based"
    revenue_records: list[RevenueRecord] = Field(default_factory=list)


class RevenueAnalysisNode(BaseModel):
    node_name: str
    status: AnalysisStatus
    trigger: str
    analysis: str
    conclusion: str
    requires_review: bool = False
    review_reason: str | None = None
    confidence_level: ConfidenceLevel | None = None
    supporting_fields: list[str] = Field(default_factory=list)


class RevenueCoverage(BaseModel):
    contract_level_analysis: bool
    revenue_record_analysis: bool
    project_context_available: bool
    analyzed_nodes: list[str] = Field(default_factory=list)
    skipped_nodes: list[str] = Field(default_factory=list)


class RevenueRecognitionResponse(BaseModel):
    recognition_run_id: str
    project_id: str
    contract_evidence_id: str
    evidence_id: str | None
    status: AnalysisStatus
    analyzer_type: AnalyzerType
    analyzer_version: str
    coverage: RevenueCoverage
    nodes: list[RevenueAnalysisNode]
    limitations: list[str]
    impact: str
    conclusion: str | None
    failure_reason: str | None
    created_at: datetime
    trace_id: str


class RevenueRecognitionListResponse(BaseModel):
    items: list[RevenueRecognitionResponse]
    total: int
