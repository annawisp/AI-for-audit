from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas.procedure_dependency import (
    DependencyEdge,
    DependencyImpact,
    DependencyNode,
)
from app.schemas.procedure_state import ProcedureExecutionStatus

GRAPH_VERSION = "procedure_dependency_graph_v1"
DEFAULT_GRAPH_PATH = Path(__file__).with_name("procedure_dependency_graph.json")
IMPACT_SOURCE_STATUSES = {
    "PARTIAL",
    "NOT_APPLICABLE",
    "NOT_PERFORMED",
    "BLOCKED",
    "ABSTAINED",
}


class ProcedureDependencyGraphConfigError(ValueError):
    """Raised when dependency graph configuration is invalid."""


class ProcedureDependencyNodeNotFoundError(ValueError):
    """Raised when a dependency graph node is not registered."""


def list_dependency_graph(
    graph_path: Path | str | None = None,
) -> tuple[str, list[DependencyNode], list[DependencyEdge]]:
    return load_dependency_graph(graph_path)


def get_dependency_node(
    node_id: str,
    graph_path: Path | str | None = None,
) -> DependencyNode | None:
    _, nodes, _ = load_dependency_graph(graph_path)
    return {node.node_id: node for node in nodes}.get(node_id)


def get_upstream_dependencies(
    node_id: str,
    graph_path: Path | str | None = None,
) -> tuple[DependencyNode, list[DependencyEdge], list[DependencyNode]]:
    graph_version, nodes, edges = load_dependency_graph(graph_path)
    del graph_version
    nodes_by_id = {node.node_id: node for node in nodes}
    node = _get_required_node(node_id, nodes_by_id)
    upstream_edges = [edge for edge in edges if edge.to_node_id == node_id]
    upstream_nodes = [nodes_by_id[edge.from_node_id] for edge in upstream_edges]
    return node, upstream_edges, upstream_nodes


def get_downstream_dependencies(
    node_id: str,
    graph_path: Path | str | None = None,
) -> tuple[DependencyNode, list[DependencyEdge], list[DependencyNode]]:
    graph_version, nodes, edges = load_dependency_graph(graph_path)
    del graph_version
    nodes_by_id = {node.node_id: node for node in nodes}
    node = _get_required_node(node_id, nodes_by_id)
    downstream_edges = [edge for edge in edges if edge.from_node_id == node_id]
    downstream_nodes = [nodes_by_id[edge.to_node_id] for edge in downstream_edges]
    return node, downstream_edges, downstream_nodes


def analyze_dependency_impact(
    *,
    node_statuses: dict[str, ProcedureExecutionStatus],
    graph_path: Path | str | None = None,
) -> tuple[str, list[DependencyImpact], list[DependencyNode]]:
    graph_version, nodes, edges = load_dependency_graph(graph_path)
    nodes_by_id = {node.node_id: node for node in nodes}
    for node_id in node_statuses:
        _get_required_node(node_id, nodes_by_id)

    outgoing_edges = _outgoing_edges(edges)
    impacts_by_node: dict[str, DependencyImpact] = {}
    queue: list[tuple[str, ProcedureExecutionStatus, list[str], str]] = [
        (node_id, status, [node_id], node_id)
        for node_id, status in node_statuses.items()
        if status in IMPACT_SOURCE_STATUSES
    ]

    while queue:
        source_node_id, source_status, path, root_source_node_id = queue.pop(0)
        for edge in outgoing_edges.get(source_node_id, []):
            recommended_status = _recommended_status(source_status, edge)
            if recommended_status is None:
                continue
            next_path = [*path, edge.to_node_id]
            impact = DependencyImpact(
                node_id=edge.to_node_id,
                node_name=nodes_by_id[edge.to_node_id].node_name,
                recommended_status=recommended_status,
                dependency_type=edge.dependency_type,
                failure_effect=edge.failure_effect,
                source_node_id=root_source_node_id,
                source_status=node_statuses.get(root_source_node_id, source_status),
                dependency_path=next_path,
                impact_reason=_impact_reason(edge, source_status, recommended_status),
            )
            previous_impact = impacts_by_node.get(edge.to_node_id)
            if previous_impact is None or _impact_rank(
                recommended_status
            ) > _impact_rank(previous_impact.recommended_status):
                impacts_by_node[edge.to_node_id] = impact
                queue.append((edge.to_node_id, recommended_status, next_path, root_source_node_id))

    impacted_node_ids = set(impacts_by_node)
    source_node_ids = set(node_statuses)
    unaffected_nodes = [
        node
        for node in nodes
        if node.node_id not in impacted_node_ids and node.node_id not in source_node_ids
    ]
    impacts = sorted(impacts_by_node.values(), key=lambda item: item.node_id)
    return graph_version, impacts, unaffected_nodes


def load_dependency_graph(
    graph_path: Path | str | None = None,
) -> tuple[str, list[DependencyNode], list[DependencyEdge]]:
    if graph_path is None:
        return _load_default_dependency_graph()
    return _load_dependency_graph_from_path(Path(graph_path))


@lru_cache(maxsize=1)
def _load_default_dependency_graph() -> tuple[str, list[DependencyNode], list[DependencyEdge]]:
    return _load_dependency_graph_from_path(DEFAULT_GRAPH_PATH)


def _load_dependency_graph_from_path(
    graph_path: Path,
) -> tuple[str, list[DependencyNode], list[DependencyEdge]]:
    try:
        raw_config = json.loads(graph_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ProcedureDependencyGraphConfigError(
            f"dependency graph config cannot be read: {graph_path}"
        ) from error
    except json.JSONDecodeError as error:
        raise ProcedureDependencyGraphConfigError(
            f"dependency graph config is not valid JSON: {error.msg}"
        ) from error

    if not isinstance(raw_config, dict):
        raise ProcedureDependencyGraphConfigError(
            "dependency graph config must be a JSON object"
        )
    graph_version = str(raw_config.get("graph_version") or GRAPH_VERSION)
    nodes = _parse_nodes(raw_config.get("nodes"))
    edges = _parse_edges(raw_config.get("edges"))
    _validate_dependency_graph(nodes, edges)
    return graph_version, nodes, edges


def _parse_nodes(raw_nodes: Any) -> list[DependencyNode]:
    if not isinstance(raw_nodes, list):
        raise ProcedureDependencyGraphConfigError("dependency graph nodes must be a list")
    nodes: list[DependencyNode] = []
    for index, node_data in enumerate(raw_nodes, start=1):
        try:
            nodes.append(DependencyNode.model_validate(node_data))
        except ValidationError as error:
            raise ProcedureDependencyGraphConfigError(
                f"dependency graph node #{index} failed schema validation"
            ) from error
    return nodes


def _parse_edges(raw_edges: Any) -> list[DependencyEdge]:
    if not isinstance(raw_edges, list):
        raise ProcedureDependencyGraphConfigError("dependency graph edges must be a list")
    edges: list[DependencyEdge] = []
    for index, edge_data in enumerate(raw_edges, start=1):
        try:
            edges.append(DependencyEdge.model_validate(edge_data))
        except ValidationError as error:
            raise ProcedureDependencyGraphConfigError(
                f"dependency graph edge #{index} failed schema validation"
            ) from error
    return edges


def _validate_dependency_graph(
    nodes: list[DependencyNode],
    edges: list[DependencyEdge],
) -> None:
    node_ids = [node.node_id for node in nodes]
    duplicate_node_ids = _duplicates(node_ids)
    if duplicate_node_ids:
        raise ProcedureDependencyGraphConfigError(
            "duplicate dependency node_id: " + ", ".join(duplicate_node_ids)
        )

    edge_ids = [edge.edge_id for edge in edges]
    duplicate_edge_ids = _duplicates(edge_ids)
    if duplicate_edge_ids:
        raise ProcedureDependencyGraphConfigError(
            "duplicate dependency edge_id: " + ", ".join(duplicate_edge_ids)
        )

    node_id_set = set(node_ids)
    for edge in edges:
        if edge.from_node_id not in node_id_set:
            raise ProcedureDependencyGraphConfigError(
                f"{edge.edge_id} references unknown from_node_id: {edge.from_node_id}"
            )
        if edge.to_node_id not in node_id_set:
            raise ProcedureDependencyGraphConfigError(
                f"{edge.edge_id} references unknown to_node_id: {edge.to_node_id}"
            )


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicated: set[str] = set()
    for value in values:
        if value in seen:
            duplicated.add(value)
        seen.add(value)
    return sorted(duplicated)


def _get_required_node(
    node_id: str,
    nodes_by_id: dict[str, DependencyNode],
) -> DependencyNode:
    node = nodes_by_id.get(node_id)
    if node is None:
        raise ProcedureDependencyNodeNotFoundError(node_id)
    return node


def _outgoing_edges(edges: list[DependencyEdge]) -> dict[str, list[DependencyEdge]]:
    outgoing: dict[str, list[DependencyEdge]] = {}
    for edge in edges:
        outgoing.setdefault(edge.from_node_id, []).append(edge)
    return outgoing


def _recommended_status(
    source_status: ProcedureExecutionStatus,
    edge: DependencyEdge,
) -> ProcedureExecutionStatus | None:
    if edge.dependency_type == "informational" or edge.failure_effect == "NONE":
        return None
    if edge.dependency_type in {"optional", "conditional"}:
        if source_status == "NOT_APPLICABLE":
            return None
        return "PARTIAL"
    if source_status == "ABSTAINED":
        return "ABSTAINED" if edge.failure_effect == "ABSTAINED" else "BLOCKED"
    if source_status == "NOT_APPLICABLE":
        return "NOT_APPLICABLE"
    if source_status == "PARTIAL":
        return "PARTIAL"
    return "BLOCKED"


def _impact_reason(
    edge: DependencyEdge,
    source_status: ProcedureExecutionStatus,
    recommended_status: ProcedureExecutionStatus,
) -> str:
    return (
        f"{edge.to_node_id} is recommended as {recommended_status} because "
        f"{edge.from_node_id} is {source_status} through a "
        f"{edge.dependency_type} dependency."
    )


def _impact_rank(status: ProcedureExecutionStatus) -> int:
    return {
        "NOT_STARTED": 0,
        "READY": 1,
        "RUNNING": 1,
        "COMPLETED": 1,
        "PARTIAL": 2,
        "NOT_APPLICABLE": 3,
        "NOT_PERFORMED": 4,
        "BLOCKED": 5,
        "ABSTAINED": 6,
    }[status]
