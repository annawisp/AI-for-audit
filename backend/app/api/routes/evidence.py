from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import get_settings
from app.schemas.error import ErrorResponse
from app.schemas.evidence import (
    EvidenceCreate,
    EvidenceListResponse,
    EvidenceResponse,
    EvidenceStatusUpdate,
    is_allowed_judgment_transition,
)
from app.services.repository import AuditRepository

router = APIRouter(prefix="/projects/{project_id}/evidence", tags=["evidence"])


def _trace_id(request: Request) -> str:
    return request.state.trace_id


def _evidence_response(row: dict[str, Any], trace_id: str) -> EvidenceResponse:
    return EvidenceResponse(**row, trace_id=trace_id)


def _error(status_code: int, request: Request, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(code=code, message=message, trace_id=_trace_id(request)).model_dump(),
    )


@router.post(
    "",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an evidence object",
)
def create_evidence(
    project_id: str,
    payload: EvidenceCreate,
    request: Request,
) -> EvidenceResponse:
    repository = AuditRepository(get_settings())
    if repository.get_project(project_id) is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "project_not_found",
            "Project was not found",
        )
    if payload.document_id and repository.get_document(project_id, payload.document_id) is None:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            request,
            "document_not_found",
            "Document was not found for this project",
        )
    if payload.procedure_id and repository.get_procedure(project_id, payload.procedure_id) is None:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            request,
            "procedure_not_found",
            "Procedure was not found for this project",
        )

    evidence = repository.create_evidence(
        project_id=project_id,
        procedure_id=payload.procedure_id,
        document_id=payload.document_id,
        source=payload.source,
        extracted_value=payload.extracted_value,
        conclusion=payload.conclusion,
        execution_status=payload.execution_status,
        node_status=payload.node_status,
        judgment_status=payload.judgment_status,
        confidence=payload.confidence,
        model_confidence=payload.model_confidence,
        confidence_level=payload.confidence_level,
        confidence_basis=payload.confidence_basis,
        reviewer=payload.reviewer,
    )
    return _evidence_response(evidence, _trace_id(request))


@router.get("", response_model=EvidenceListResponse, summary="List project evidence")
def list_evidence(project_id: str, request: Request) -> EvidenceListResponse:
    repository = AuditRepository(get_settings())
    if repository.get_project(project_id) is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "project_not_found",
            "Project was not found",
        )
    return EvidenceListResponse(
        items=[
            _evidence_response(row, _trace_id(request))
            for row in repository.list_evidence(project_id)
        ],
        trace_id=_trace_id(request),
    )


@router.get(
    "/{evidence_id}",
    response_model=EvidenceResponse,
    summary="Get the latest evidence object",
)
def get_evidence(project_id: str, evidence_id: str, request: Request) -> EvidenceResponse:
    repository = AuditRepository(get_settings())
    evidence = repository.get_evidence(project_id, evidence_id)
    if evidence is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "evidence_not_found",
            "Evidence object was not found",
        )
    return _evidence_response(evidence, _trace_id(request))


@router.get(
    "/{evidence_id}/versions/{object_version}",
    response_model=EvidenceResponse,
    summary="Get a historical evidence object version",
)
def get_evidence_version(
    project_id: str,
    evidence_id: str,
    object_version: int,
    request: Request,
) -> EvidenceResponse:
    repository = AuditRepository(get_settings())
    evidence = repository.get_evidence_version(
        project_id=project_id,
        evidence_id=evidence_id,
        object_version=object_version,
    )
    if evidence is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "evidence_version_not_found",
            "Evidence object version was not found",
        )
    return _evidence_response(evidence, _trace_id(request))


@router.patch(
    "/{evidence_id}/status",
    response_model=EvidenceResponse,
    summary="Update evidence object status and review fields",
)
def update_evidence_status(
    project_id: str,
    evidence_id: str,
    payload: EvidenceStatusUpdate,
    request: Request,
) -> EvidenceResponse:
    repository = AuditRepository(get_settings())
    current = repository.get_evidence(project_id, evidence_id)
    if current is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "evidence_not_found",
            "Evidence object was not found",
        )

    if payload.judgment_status and not is_allowed_judgment_transition(
        str(current["judgment_status"]),
        payload.judgment_status,
    ):
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            request,
            "invalid_judgment_transition",
            "Judgment status transition is not allowed",
        )

    evidence = repository.update_evidence(
        project_id=project_id,
        evidence_id=evidence_id,
        updates=payload.model_dump(exclude_unset=True),
    )
    return _evidence_response(evidence, _trace_id(request))
