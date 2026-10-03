from typing import Literal

from pydantic import BaseModel, Field

InputKind = Literal["required", "optional", "dependent"]
ReadinessStatus = Literal["READY", "PARTIAL", "BLOCKED", "NOT_APPLICABLE"]
ReadinessStrategy = Literal[
    "all_required_inputs",
    "all_required_inputs_and_upstream",
    "required_inputs_with_partial_optional",
    "at_least_one_relevant_input",
]


class ProcedureInput(BaseModel):
    input_id: str
    display_name: str
    kind: InputKind
    description: str
    source: str | None = None


class CapabilityBinding(BaseModel):
    capability_id: str
    capability_name: str
    source: str
    produces_evidence_source: str | None = None


class OutputSchemaRef(BaseModel):
    schema_id: str
    evidence_source: str
    description: str


class ExecutionPolicy(BaseModel):
    readiness_strategy: ReadinessStrategy
    allow_partial_execution: bool
    partial_when_optional_missing: bool = False
    minimum_required_input_groups: list[list[str]] = Field(default_factory=list)
    blocked_statuses: list[str] = Field(default_factory=list)


class ProcedureDefinition(BaseModel):
    procedure_id: str
    procedure_name: str
    procedure_category: str
    version: str
    required_inputs: list[ProcedureInput] = Field(default_factory=list)
    optional_inputs: list[ProcedureInput] = Field(default_factory=list)
    dependent_inputs: list[ProcedureInput] = Field(default_factory=list)
    upstream_dependencies: list[str] = Field(default_factory=list)
    capabilities: list[CapabilityBinding] = Field(default_factory=list)
    output_schema: OutputSchemaRef
    execution_policy: ExecutionPolicy


class ProcedureRegistryListResponse(BaseModel):
    items: list[ProcedureDefinition]
    total: int
    trace_id: str


class ProcedureRegistryResponse(BaseModel):
    procedure: ProcedureDefinition
    trace_id: str


class ProcedureReadinessRequest(BaseModel):
    available_inputs: dict[str, bool] = Field(default_factory=dict)
    completed_procedures: list[str] = Field(default_factory=list)
    mark_not_applicable: bool = False
    not_applicable_reason: str | None = None


class ProcedureReadinessResponse(BaseModel):
    procedure_id: str
    procedure_name: str
    readiness_status: ReadinessStatus
    ready_inputs: list[str]
    missing_required_inputs: list[str]
    missing_optional_inputs: list[str]
    missing_dependent_inputs: list[str]
    satisfied_upstream_dependencies: list[str]
    missing_upstream_dependencies: list[str]
    blocked_reason: str | None
    explanation: str
    trace_id: str
