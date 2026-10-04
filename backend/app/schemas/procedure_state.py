from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ProcedureExecutionStatus = Literal[
    "NOT_STARTED",
    "READY",
    "RUNNING",
    "COMPLETED",
    "PARTIAL",
    "NOT_APPLICABLE",
    "NOT_PERFORMED",
    "BLOCKED",
    "ABSTAINED",
]
ProcedureStateSource = Literal["system", "auditor", "project_config", "capability"]
AbstentionLevel = Literal["field", "node", "procedure"]


class ProcedureStateInitializeRequest(BaseModel):
    reset_existing: bool = False


class ProcedureStateEvaluateRequest(BaseModel):
    available_inputs: dict[str, bool] = Field(default_factory=dict)
    completed_procedures: list[str] = Field(default_factory=list)
    related_evidence_ids: list[str] = Field(default_factory=list)


class ProcedureStateTransitionRequest(BaseModel):
    to_status: ProcedureExecutionStatus
    reason: str = Field(min_length=1, max_length=2000)
    source_type: ProcedureStateSource
    actor: str | None = Field(default=None, max_length=200)
    abstention_level: AbstentionLevel | None = None
    related_evidence_ids: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manual_status_context(self) -> "ProcedureStateTransitionRequest":
        if self.to_status == "NOT_APPLICABLE" and self.source_type not in {
            "auditor",
            "project_config",
        }:
            raise ValueError("NOT_APPLICABLE must be set by auditor or project_config")
        if self.to_status == "NOT_PERFORMED" and self.source_type not in {
            "auditor",
            "project_config",
        }:
            raise ValueError("NOT_PERFORMED must be set by auditor or project_config")
        if self.to_status == "ABSTAINED" and self.abstention_level is None:
            raise ValueError("abstention_level is required when status is ABSTAINED")
        if self.to_status == "COMPLETED" and not self.related_evidence_ids:
            raise ValueError("related_evidence_ids is required when status is COMPLETED")
        return self


class ProcedureStateResponse(BaseModel):
    state_id: str
    project_id: str
    procedure_id: str
    procedure_name: str
    status: ProcedureExecutionStatus
    status_reason: str
    source_type: ProcedureStateSource
    abstention_level: AbstentionLevel | None
    related_evidence_ids: list[str]
    blocked_by: list[str]
    created_at: datetime
    updated_at: datetime
    trace_id: str


class ProcedureStateListResponse(BaseModel):
    items: list[ProcedureStateResponse]
    total: int
    trace_id: str


class ProcedureStateTransitionResponse(BaseModel):
    transition_id: str
    state_id: str
    project_id: str
    procedure_id: str
    from_status: ProcedureExecutionStatus | None
    to_status: ProcedureExecutionStatus
    reason: str
    triggered_by: ProcedureStateSource
    actor: str | None
    created_at: datetime
    trace_id: str


class ProcedureStateTransitionListResponse(BaseModel):
    items: list[ProcedureStateTransitionResponse]
    total: int
    trace_id: str
