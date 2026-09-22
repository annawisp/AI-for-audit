from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RevenueRecord(BaseModel):
    record_id: str | None = None
    recognition_date: str | None = None
    amount: str | float | int | None = None
    description: str | None = None


class RevenueRiskRequest(BaseModel):
    contract_evidence_id: str | None = None
    revenue_recognition_evidence_id: str | None = None
    revenue_records: list[RevenueRecord] = Field(default_factory=list)
    engine_type: Literal["rule_based"] = "rule_based"
    enable_semantic_judgment: bool = False


class RevenueRiskSignal(BaseModel):
    signal_id: str
    name: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    status: Literal["COMPLETED", "REQUIRES_REVIEW", "ABSTAINED"]
    rationale: str
    source: str


class RevenueRiskCoverage(BaseModel):
    contract_evidence: bool = False
    revenue_recognition_evidence: bool = False
    revenue_record_analysis: bool = False
    coverage_ratio: float = 0.0
    rule_coverage_ratio: float = 0.0
    semantic_judgment_coverage: float = 0.0


class RevenueRiskResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    project_id: str
    evidence_id: str
    status: Literal["COMPLETED", "REQUIRES_REVIEW"]
    overall_risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    coverage: RevenueRiskCoverage
    coverage_ratio: float
    rule_coverage_ratio: float
    semantic_judgment_coverage: float
    risk_signals: list[RevenueRiskSignal]
    limitations: list[str]
    conclusion: str
    source_evidence_ids: list[str]
    engine_type: str = "rule_based"
    rules_version: str
    llm_judgment_status: str
    trace_id: str


class RevenueRiskListResponse(BaseModel):
    items: list[RevenueRiskResponse]
    total: int


RevenueRiskEvidenceValue = dict[str, Any]
