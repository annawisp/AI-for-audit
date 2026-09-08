"""Project Context MVP (TASK-201) HTTP routes.

Endpoints:

- POST   /projects/{project_id}/context              create/append version
- GET    /projects/{project_id}/context              current version
- GET    /projects/{project_id}/context/versions     version list (metadata)
- GET    /projects/{project_id}/context/versions/{version}  one snapshot
- GET    /projects/{project_id}/context/readiness    start readiness report
"""

import json
from collections import Counter
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import get_settings
from app.schemas.error import ErrorResponse
from app.schemas.project_context import (
    ProjectContextPayload,
    ProjectContextReadinessResponse,
    ProjectContextVersionListResponse,
    ProjectContextVersionMeta,
    ProjectContextVersionResponse,
    ProjectContextWrite,
)
from app.services.project_context import build_readiness, seed_initial_payload
from app.services.repository import AuditRepository

router = APIRouter(prefix="/projects/{project_id}/context", tags=["project-context"])


def _trace_id(request: Request) -> str:
    return request.state.trace_id


def _http_error(
    status_code: int, request: Request, code: str, message: str
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(code=code, message=message, trace_id=_trace_id(request)).model_dump(),
    )


def _not_found(request: Request, code: str, message: str) -> HTTPException:
    return _http_error(status.HTTP_404_NOT_FOUND, request, code, message)


def _bad_request(request: Request, code: str, message: str) -> HTTPException:
    return _http_error(status.HTTP_400_BAD_REQUEST, request, code, message)


def _project_or_404(
    repository: AuditRepository, project_id: str, request: Request
) -> dict[str, Any]:
    project = repository.get_project(project_id)
    if project is None:
        raise _not_found(request, "project_not_found", "Project was not found")
    return project


def _version_response(row: dict[str, Any], trace_id: str) -> ProjectContextVersionResponse:
    return ProjectContextVersionResponse(
        version_id=row["version_id"],
        project_id=row["project_id"],
        version=int(row["version"]),
        payload=ProjectContextPayload.model_validate(json.loads(row["payload_json"])),
        changed_by=row["changed_by"],
        change_reason=row["change_reason"],
        changed_sections=json.loads(row["changed_sections"]),
        is_current=bool(row["is_current"]),
        created_at=row["created_at"],
        trace_id=trace_id,
    )


def _meta_response(row: dict[str, Any], trace_id: str) -> ProjectContextVersionMeta:
    return ProjectContextVersionMeta(
        version_id=row["version_id"],
        project_id=row["project_id"],
        version=int(row["version"]),
        changed_by=row["changed_by"],
        change_reason=row["change_reason"],
        changed_sections=json.loads(row["changed_sections"]),
        is_current=bool(row["is_current"]),
        created_at=row["created_at"],
    )


def _validate_contract_documents(
    payload: dict[str, Any],
    repository: AuditRepository,
    project_id: str,
    request: Request,
) -> None:
    """Reject duplicate / foreign document references before persisting."""
    document_ids = [
        entry["document_id"]
        for entry in payload.get("contracts") or []
        if entry.get("document_id")
    ]
    duplicates = sorted(
        {document_id for document_id, count in Counter(document_ids).items() if count > 1}
    )
    if duplicates:
        raise _bad_request(
            request,
            "duplicate_document_reference",
            f"Document(s) {', '.join(duplicates)} referenced more than once",
        )
    for document_id in document_ids:
        if repository.get_document(project_id, document_id) is None:
            raise _bad_request(
                request,
                "document_not_in_project",
                f"Document {document_id} does not belong to the project",
            )


@router.post(
    "",
    response_model=ProjectContextVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or update the project context (new version)",
)
def create_or_update_project_context(
    project_id: str, body: ProjectContextWrite, request: Request
) -> ProjectContextVersionResponse:
    repository = AuditRepository(get_settings())
    project = _project_or_404(repository, project_id, request)

    payload_data = body.payload.model_dump(mode="json")
    _validate_contract_documents(payload_data, repository, project_id, request)

    if repository.get_project_context(project_id) is None:
        payload_data = seed_initial_payload(payload_data, project)

    row = repository.create_project_context_version(
        project_id=project_id,
        payload=payload_data,
        changed_by=body.changed_by,
        change_reason=body.change_reason,
    )
    return _version_response(row, _trace_id(request))


@router.get(
    "",
    response_model=ProjectContextVersionResponse,
    summary="Get the current project context version",
)
def get_current_project_context(
    project_id: str, request: Request
) -> ProjectContextVersionResponse:
    repository = AuditRepository(get_settings())
    _project_or_404(repository, project_id, request)
    row = repository.get_project_context(project_id)
    if row is None:
        raise _not_found(
            request,
            "context_not_found",
            "Project context has not been created yet; POST the first payload to create version 1",
        )
    return _version_response(row, _trace_id(request))


@router.get(
    "/readiness",
    response_model=ProjectContextReadinessResponse,
    summary="Report whether the project can start with the current context",
)
def get_project_context_readiness(
    project_id: str, request: Request
) -> ProjectContextReadinessResponse:
    repository = AuditRepository(get_settings())
    _project_or_404(repository, project_id, request)
    row = repository.get_project_context(project_id)
    readiness = build_readiness(project_id, row)
    return ProjectContextReadinessResponse(**readiness, trace_id=_trace_id(request))


@router.get(
    "/versions",
    response_model=ProjectContextVersionListResponse,
    summary="List project context versions (metadata only)",
)
def list_project_context_versions(
    project_id: str, request: Request
) -> ProjectContextVersionListResponse:
    repository = AuditRepository(get_settings())
    _project_or_404(repository, project_id, request)
    rows = repository.list_project_context_versions(project_id)
    return ProjectContextVersionListResponse(
        items=[_meta_response(row, _trace_id(request)) for row in rows],
        trace_id=_trace_id(request),
    )


@router.get(
    "/versions/{version}",
    response_model=ProjectContextVersionResponse,
    summary="Get one historical project context snapshot",
)
def get_project_context_version(
    project_id: str, version: int, request: Request
) -> ProjectContextVersionResponse:
    repository = AuditRepository(get_settings())
    _project_or_404(repository, project_id, request)
    row = repository.get_project_context_version(project_id, version)
    if row is None:
        raise _not_found(
            request,
            "context_version_not_found",
            f"Project context version {version} was not found",
        )
    return _version_response(row, _trace_id(request))
