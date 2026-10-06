from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.procedure_state import ProcedureExecutionStatus

DependencyNodeType = Literal["procedure", "node", "field", "evidence", "dataset"]
DependencyType = Literal["required", "optional", "conditional", "informational"]
FailureEffect = Literal["BLOCKED", "PARTIAL", "ABSTAINED", "NOT_APPLICABLE", "NONE"]


class DependencyNode(BaseModel):
    node_id: str = Field(min_length=1)
    node_name: str = Field(min_length=1)
    node_type: DependencyNodeType
    procedure_id: str | None = None
    description: str


class DependencyEdge(BaseModel):
    edge_id: str = Field(min_length=1)
    from_node_id: str = Field(min_length=1)
    to_node_id: str = Field(min_length=1)
    dependency_type: DependencyType
    failure_effect: FailureEffect
    description: str


class DependencyGraphResponse(BaseModel):
    graph_version: str
    nodes: list[DependencyNode]
    edges: list[DependencyEdge]
    total_nodes: int
    total_edges: int
    trace_id: str


class DependencyNodeQueryResponse(BaseModel):
    graph_version: str
    node: DependencyNode
    edges: list[DependencyEdge]
    related_nodes: list[DependencyNode]
    trace_id: str


class DependencyImpactRequest(BaseModel):
    node_statuses: dict[str, ProcedureExecutionStatus] = Field(default_factory=dict)


class DependencyImpact(BaseModel):
    node_id: str
    node_name: str
    recommended_status: ProcedureExecutionStatus
    dependency_type: DependencyType
    failure_effect: FailureEffect
    source_node_id: str
    source_status: ProcedureExecutionStatus
    dependency_path: list[str]
    impact_reason: str


class DependencyImpactResponse(BaseModel):
    graph_version: str
    input_node_statuses: dict[str, ProcedureExecutionStatus]
    impacted_nodes: list[DependencyImpact]
    unaffected_nodes: list[DependencyNode]
    total_impacted: int
    total_unaffected: int
    trace_id: str
