from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import get_settings
from app.orchestrator.procedure_dependency_graph import (
    ProcedureDependencyNodeNotFoundError,
    analyze_dependency_impact,
    get_downstream_dependencies,
    get_upstream_dependencies,
    list_dependency_graph,
)
from app.schemas.error import ErrorResponse
from app.schemas.procedure_dependency import (
    DependencyGraphResponse,
    DependencyImpactRequest,
    DependencyImpactResponse,
    DependencyNodeQueryResponse,
)
from app.services.repository import AuditRepository

router = APIRouter(prefix="/procedure-dependencies", tags=["procedure-dependencies"])
project_router = APIRouter(
    prefix="/projects/{project_id}/procedure-dependencies",
    tags=["procedure-dependencies"],
)


def _trace_id(request: Request) -> str:
    return request.state.trace_id


def _error(status_code: int, request: Request, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(
            code=code,
            message=message,
            trace_id=_trace_id(request),
        ).model_dump(),
    )


@router.get(
    "",
    response_model=DependencyGraphResponse,
    summary="List the default procedure dependency graph",
)
async def get_procedure_dependency_graph(request: Request) -> DependencyGraphResponse:
    graph_version, nodes, edges = list_dependency_graph()
    return DependencyGraphResponse(
        graph_version=graph_version,
        nodes=nodes,
        edges=edges,
        total_nodes=len(nodes),
        total_edges=len(edges),
        trace_id=_trace_id(request),
    )


@router.get(
    "/{node_id}/upstream",
    response_model=DependencyNodeQueryResponse,
    summary="List upstream dependencies for one graph node",
)
async def get_node_upstream_dependencies(
    node_id: str,
    request: Request,
) -> DependencyNodeQueryResponse:
    return _node_query_response(
        node_id=node_id,
        direction="upstream",
        request=request,
    )


@router.get(
    "/{node_id}/downstream",
    response_model=DependencyNodeQueryResponse,
    summary="List downstream dependencies for one graph node",
)
async def get_node_downstream_dependencies(
    node_id: str,
    request: Request,
) -> DependencyNodeQueryResponse:
    return _node_query_response(
        node_id=node_id,
        direction="downstream",
        request=request,
    )


@project_router.post(
    "/impact",
    response_model=DependencyImpactResponse,
    summary="Analyze local failure impact for project procedure nodes",
)
async def analyze_project_dependency_impact(
    project_id: str,
    payload: DependencyImpactRequest,
    request: Request,
) -> DependencyImpactResponse:
    repository = AuditRepository(get_settings())
    if repository.get_project(project_id) is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "project_not_found",
            "Project was not found.",
        )
    try:
        graph_version, impacted_nodes, unaffected_nodes = analyze_dependency_impact(
            node_statuses=payload.node_statuses,
        )
    except ProcedureDependencyNodeNotFoundError as error:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "dependency_node_not_found",
            f"Dependency node {error} was not found.",
        ) from error
    return DependencyImpactResponse(
        graph_version=graph_version,
        input_node_statuses=payload.node_statuses,
        impacted_nodes=impacted_nodes,
        unaffected_nodes=unaffected_nodes,
        total_impacted=len(impacted_nodes),
        total_unaffected=len(unaffected_nodes),
        trace_id=_trace_id(request),
    )


def _node_query_response(
    *,
    node_id: str,
    direction: str,
    request: Request,
) -> DependencyNodeQueryResponse:
    try:
        if direction == "upstream":
            node, edges, related_nodes = get_upstream_dependencies(node_id)
        else:
            node, edges, related_nodes = get_downstream_dependencies(node_id)
    except ProcedureDependencyNodeNotFoundError as error:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "dependency_node_not_found",
            f"Dependency node {error} was not found.",
        ) from error
    graph_version, _, _ = list_dependency_graph()
    return DependencyNodeQueryResponse(
        graph_version=graph_version,
        node=node,
        edges=edges,
        related_nodes=related_nodes,
        trace_id=_trace_id(request),
    )
