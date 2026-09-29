from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ReconciliationStatus = Literal[
    "COMPLETE",
    "PARTIAL",
    "INSUFFICIENT_DATA",
    "NOT_PROVIDED",
    "NOT_APPLICABLE",
    "REQUIRES_REVIEW",
    "CONFLICTING_EVIDENCE",
    "CONFLICTING",
    "UNMATCHED",
    "AMBIGUOUS",
    "LOW_CONFIDENCE",
]
RunStatus = Literal["COMPLETE", "PARTIAL", "INSUFFICIENT_DATA"]
Severity = Literal["low", "medium", "high"]
LinkConfidence = Literal["HIGH", "MEDIUM", "LOW", "NONE"]
MatchStatus = Literal[
    "MATCHED",
    "UNMATCHED",
    "NOT_PROVIDED",
    "INSUFFICIENT_DATA",
    "LOW_CONFIDENCE",
    "AMBIGUOUS",
    "CONFLICTING",
]
EngineType = Literal["rule_based"]


class ReconciliationRecord(BaseModel):
    record_id: str | None = None
    contract_reference: str | None = None
    customer_name: str | None = None
    invoice_number: str | None = None
    recognition_date: str | None = None
    due_date: str | None = None
    receipt_date: str | None = None
    amount: Any = None
    description: str | None = None
    extra_fields: dict[str, Any] = Field(default_factory=dict)


class DataReconciliationRequest(BaseModel):
    contract_evidence_id: str | None = None
    revenue_recognition_evidence_id: str | None = None
    revenue_risk_evidence_id: str | None = None
    engine_type: EngineType = "rule_based"
    audit_period_start: str | None = None
    audit_period_end: str | None = None
    revenue_records: list[ReconciliationRecord] = Field(default_factory=list)
    receivable_records: list[ReconciliationRecord] = Field(default_factory=list)
    cash_receipt_records: list[ReconciliationRecord] = Field(default_factory=list)


class EvidenceReference(BaseModel):
    evidence_id: str
    source: str
    field_name: str | None = None


class MatchedLink(BaseModel):
    source_record_id: str | None = None
    target_record_id: str | None = None
    source_type: str
    target_type: str
    match_status: MatchStatus
    link_method: str
    link_confidence: LinkConfidence
    amount_difference: float | None = None
    date_difference_days: int | None = None
    basis: str


class ReconciliationException(BaseModel):
    exception_id: str
    exception_type: str
    severity: Severity
    status: ReconciliationStatus
    description: str
    basis: str
    record_ids: list[str] = Field(default_factory=list)
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    recommendation: str
    recommended_follow_up: str
    is_audit_conclusion: bool = False
    match_status: MatchStatus | None = None
    requires_review: bool = False


class ReconciliationNode(BaseModel):
    node_id: str
    node_name: str
    status: ReconciliationStatus
    link_method: str
    link_confidence: LinkConfidence
    matched_count: int = 0
    unmatched_count: int = 0
    exceptions: list[ReconciliationException] = Field(default_factory=list)
    basis: str
    limitations: list[str] = Field(default_factory=list)


class ReconciliationCoverage(BaseModel):
    total_nodes: int
    assessable_nodes: int
    insufficient_data_nodes: int
    not_provided_nodes: int
    not_applicable_nodes: int
    coverage_ratio: float
    excluded_node_ids: list[str] = Field(default_factory=list)


class DataReconciliationResponse(BaseModel):
    reconciliation_run_id: str
    project_id: str
    contract_evidence_id: str | None
    revenue_recognition_evidence_id: str | None
    revenue_risk_evidence_id: str | None
    evidence_id: str | None
    source_evidence_ids: list[str]
    status: RunStatus
    overall_exception_level: Severity | None
    coverage: ReconciliationCoverage
    coverage_ratio: float
    nodes: list[ReconciliationNode]
    matched_links: list[MatchedLink]
    exceptions: list[ReconciliationException]
    limitations: list[str]
    requires_review: bool
    engine_type: EngineType
    rules_version: str
    conclusion: str
    created_at: datetime
    trace_id: str


class DataReconciliationListResponse(BaseModel):
    items: list[DataReconciliationResponse]
    total: int
