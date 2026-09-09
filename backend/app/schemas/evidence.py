from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ExecutionStatus = Literal["not_started", "running", "completed", "failed", "abstained"]
NodeStatus = Literal["draft", "ready", "partial", "blocked", "abstained", "completed"]
JudgmentStatus = Literal[
    "AI_GENERATED",
    "PENDING_REVIEW",
    "CONFIRMED",
    "MODIFIED",
    "REJECTED",
    "NEED_MORE_EVIDENCE",
]
ConfidenceLevel = Literal["low", "medium", "high"]
FINAL_JUDGMENT_STATUSES = {"CONFIRMED", "MODIFIED", "REJECTED"}
JUDGMENT_TRANSITIONS: dict[str, set[str]] = {
    "AI_GENERATED": {"PENDING_REVIEW"},
    "PENDING_REVIEW": {
        "CONFIRMED",
        "MODIFIED",
        "REJECTED",
        "NEED_MORE_EVIDENCE",
    },
    "NEED_MORE_EVIDENCE": {"AI_GENERATED"},
    "CONFIRMED": set(),
    "MODIFIED": set(),
    "REJECTED": set(),
}


def is_allowed_judgment_transition(current_status: str, next_status: str) -> bool:
    if current_status == next_status:
        return True
    return next_status in JUDGMENT_TRANSITIONS[current_status]


class EvidenceCreate(BaseModel):
    procedure_id: str | None = None
    document_id: str | None = None
    source: str = Field(min_length=1, max_length=500)
    extracted_value: Any
    conclusion: str | None = Field(default=None, max_length=4000)
    execution_status: ExecutionStatus = "completed"
    node_status: NodeStatus = "ready"
    judgment_status: JudgmentStatus = "AI_GENERATED"
    confidence: float | None = Field(default=None, ge=0, le=1)
    model_confidence: float | None = Field(default=None, ge=0, le=1)
    confidence_level: ConfidenceLevel | None = None
    confidence_basis: str | None = Field(default=None, max_length=4000)
    reviewer: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_confidence_basis(self) -> "EvidenceCreate":
        if self.judgment_status in FINAL_JUDGMENT_STATUSES and not self.reviewer:
            raise ValueError("reviewer is required for final review decisions")
        if self.confidence_level and not self.confidence_basis:
            raise ValueError("confidence_basis is required when confidence_level is provided")
        return self


class EvidenceStatusUpdate(BaseModel):
    execution_status: ExecutionStatus | None = None
    node_status: NodeStatus | None = None
    judgment_status: JudgmentStatus | None = None
    conclusion: str | None = Field(default=None, max_length=4000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    model_confidence: float | None = Field(default=None, ge=0, le=1)
    confidence_level: ConfidenceLevel | None = None
    confidence_basis: str | None = Field(default=None, max_length=4000)
    reviewer: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_status_change(self) -> "EvidenceStatusUpdate":
        if self.judgment_status in FINAL_JUDGMENT_STATUSES and not self.reviewer:
            raise ValueError("reviewer is required for final review decisions")
        if self.confidence_level and not self.confidence_basis:
            raise ValueError("confidence_basis is required when confidence_level is provided")
        return self


class EvidenceResponse(BaseModel):
    evidence_id: str
    project_id: str
    procedure_id: str | None
    document_id: str | None
    source: str
    extracted_value: Any
    conclusion: str | None
    execution_status: ExecutionStatus
    node_status: NodeStatus
    judgment_status: JudgmentStatus
    confidence: float | None
    model_confidence: float | None
    confidence_level: ConfidenceLevel | None
    confidence_basis: str | None
    reviewer: str | None
    schema_version: int
    object_version: int
    timestamp: datetime
    created_at: datetime
    updated_at: datetime
    trace_id: str


class EvidenceListResponse(BaseModel):
    items: list[EvidenceResponse]
    trace_id: str
