from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import get_settings
from app.schemas.error import ErrorResponse
from app.schemas.project import ProjectCreate, ProjectListResponse, ProjectResponse
from app.services.repository import AuditRepository

router = APIRouter(prefix="/projects", tags=["projects"])


def _trace_id(request: Request) -> str:
    return request.state.trace_id


def _project_response(row: dict[str, Any], trace_id: str) -> ProjectResponse:
    return ProjectResponse(**row, trace_id=trace_id)


def not_found_error(request: Request, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ErrorResponse(code=code, message=message, trace_id=_trace_id(request)).model_dump(),
    )


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an audit project",
)
def create_project(payload: ProjectCreate, request: Request) -> ProjectResponse:
    repository = AuditRepository(get_settings())
    project = repository.create_project(
        name=payload.name,
        client_name=payload.client_name,
        audit_period_start=payload.audit_period_start,
        audit_period_end=payload.audit_period_end,
    )
    return _project_response(project, _trace_id(request))


@router.get("", response_model=ProjectListResponse, summary="List audit projects")
def list_projects(request: Request) -> ProjectListResponse:
    repository = AuditRepository(get_settings())
    return ProjectListResponse(
        items=[_project_response(row, _trace_id(request)) for row in repository.list_projects()],
        trace_id=_trace_id(request),
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get an audit project",
)
def get_project(project_id: str, request: Request) -> ProjectResponse:
    repository = AuditRepository(get_settings())
    project = repository.get_project(project_id)
    if project is None:
        raise not_found_error(request, "project_not_found", "Project was not found")
    return _project_response(project, _trace_id(request))
