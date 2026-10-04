from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import get_settings
from app.orchestrator.procedure_registry import get_procedure, list_procedures
from app.orchestrator.procedure_state_machine import (
    ProcedureStateMachineError,
    status_from_registry_readiness,
    validate_transition,
)
from app.schemas.error import ErrorResponse
from app.schemas.procedure_state import (
    ProcedureStateEvaluateRequest,
    ProcedureStateInitializeRequest,
    ProcedureStateListResponse,
    ProcedureStateResponse,
    ProcedureStateTransitionListResponse,
    ProcedureStateTransitionRequest,
    ProcedureStateTransitionResponse,
)
from app.services.procedure_state_repository import ProcedureStateRepository
from app.services.repository import AuditRepository

router = APIRouter(
    prefix="/projects/{project_id}/procedure-states",
    tags=["procedure-states"],
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


def _state_response(row: dict[str, Any], trace_id: str) -> ProcedureStateResponse:
    return ProcedureStateResponse(**row, trace_id=trace_id)


def _transition_response(
    row: dict[str, Any],
) -> ProcedureStateTransitionResponse:
    return ProcedureStateTransitionResponse(**row)


@router.post(
    "/initialize",
    response_model=ProcedureStateListResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initialize project procedure execution states from registry",
)
async def initialize_procedure_states(
    project_id: str,
    payload: ProcedureStateInitializeRequest,
    request: Request,
) -> ProcedureStateListResponse:
    audit_repository = AuditRepository(get_settings())
    state_repository = ProcedureStateRepository(get_settings())
    _load_project(audit_repository, project_id, request)
    trace_id = _trace_id(request)
    for procedure in list_procedures():
        existing = state_repository.get_procedure_state_by_procedure(
            project_id,
            procedure.procedure_id,
        )
        if existing is not None and not payload.reset_existing:
            continue
        state_repository.upsert_procedure_state(
            project_id=project_id,
            procedure_id=procedure.procedure_id,
            procedure_name=procedure.procedure_name,
            status="NOT_STARTED",
            status_reason="Procedure state initialized from registry.",
            source_type="system",
            abstention_level=None,
            related_evidence_ids=[],
            blocked_by=[],
            trace_id=trace_id,
        )
    items = [
        _state_response(row, trace_id)
        for row in state_repository.list_procedure_states(project_id)
    ]
    return ProcedureStateListResponse(items=items, total=len(items), trace_id=trace_id)


@router.get(
    "",
    response_model=ProcedureStateListResponse,
    summary="List project procedure execution states",
)
async def list_procedure_states(
    project_id: str,
    request: Request,
) -> ProcedureStateListResponse:
    audit_repository = AuditRepository(get_settings())
    state_repository = ProcedureStateRepository(get_settings())
    _load_project(audit_repository, project_id, request)
    trace_id = _trace_id(request)
    items = [
        _state_response(row, trace_id)
        for row in state_repository.list_procedure_states(project_id)
    ]
    return ProcedureStateListResponse(items=items, total=len(items), trace_id=trace_id)


@router.get(
    "/{state_id}",
    response_model=ProcedureStateResponse,
    summary="Get one procedure execution state",
)
async def get_procedure_state(
    project_id: str,
    state_id: str,
    request: Request,
) -> ProcedureStateResponse:
    audit_repository = AuditRepository(get_settings())
    state_repository = ProcedureStateRepository(get_settings())
    state_row = _load_state(
        audit_repository,
        state_repository,
        project_id,
        state_id,
        request,
    )
    return _state_response(state_row, _trace_id(request))


@router.post(
    "/{state_id}/evaluate",
    response_model=ProcedureStateResponse,
    summary="Evaluate procedure execution state from registry readiness",
)
async def evaluate_procedure_state(
    project_id: str,
    state_id: str,
    payload: ProcedureStateEvaluateRequest,
    request: Request,
) -> ProcedureStateResponse:
    audit_repository = AuditRepository(get_settings())
    state_repository = ProcedureStateRepository(get_settings())
    state_row = _load_state(
        audit_repository,
        state_repository,
        project_id,
        state_id,
        request,
    )
    procedure = get_procedure(str(state_row["procedure_id"]))
    if procedure is None:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            request,
            "procedure_not_found",
            "Procedure was not found in registry.",
        )
    next_status, reason, blocked_by = status_from_registry_readiness(
        procedure=procedure,
        available_inputs=payload.available_inputs,
        completed_procedures=payload.completed_procedures,
    )
    _validate_transition_or_raise(
        request=request,
        from_status=str(state_row["status"]),
        to_status=next_status,
        source_type="system",
        reason=reason,
        abstention_level=None,
        related_evidence_ids=payload.related_evidence_ids,
    )
    updated = state_repository.update_procedure_state(
        project_id=project_id,
        state_id=state_id,
        status=next_status,
        status_reason=reason,
        source_type="system",
        abstention_level=None,
        related_evidence_ids=payload.related_evidence_ids,
        blocked_by=blocked_by,
        trace_id=_trace_id(request),
    )
    if updated is None:
        raise _state_not_found(request)
    return _state_response(updated, _trace_id(request))


@router.post(
    "/{state_id}/transition",
    response_model=ProcedureStateResponse,
    summary="Transition a procedure execution state",
)
async def transition_procedure_state(
    project_id: str,
    state_id: str,
    payload: ProcedureStateTransitionRequest,
    request: Request,
) -> ProcedureStateResponse:
    audit_repository = AuditRepository(get_settings())
    state_repository = ProcedureStateRepository(get_settings())
    state_row = _load_state(
        audit_repository,
        state_repository,
        project_id,
        state_id,
        request,
    )
    _validate_related_evidence(
        audit_repository,
        project_id,
        payload.related_evidence_ids,
        request,
    )
    _validate_transition_or_raise(
        request=request,
        from_status=str(state_row["status"]),
        to_status=payload.to_status,
        source_type=payload.source_type,
        reason=payload.reason,
        abstention_level=payload.abstention_level,
        related_evidence_ids=payload.related_evidence_ids,
    )
    updated = state_repository.update_procedure_state(
        project_id=project_id,
        state_id=state_id,
        status=payload.to_status,
        status_reason=payload.reason,
        source_type=payload.source_type,
        abstention_level=payload.abstention_level,
        related_evidence_ids=payload.related_evidence_ids,
        blocked_by=payload.blocked_by,
        actor=payload.actor,
        trace_id=_trace_id(request),
    )
    if updated is None:
        raise _state_not_found(request)
    return _state_response(updated, _trace_id(request))


@router.get(
    "/{state_id}/transitions",
    response_model=ProcedureStateTransitionListResponse,
    summary="List procedure state transition history",
)
async def list_procedure_state_transitions(
    project_id: str,
    state_id: str,
    request: Request,
) -> ProcedureStateTransitionListResponse:
    audit_repository = AuditRepository(get_settings())
    state_repository = ProcedureStateRepository(get_settings())
    _load_state(audit_repository, state_repository, project_id, state_id, request)
    trace_id = _trace_id(request)
    items = [
        _transition_response(row)
        for row in state_repository.list_procedure_state_transitions(project_id, state_id)
    ]
    return ProcedureStateTransitionListResponse(
        items=items,
        total=len(items),
        trace_id=trace_id,
    )


def _load_project(
    repository: AuditRepository,
    project_id: str,
    request: Request,
) -> dict[str, Any]:
    project = repository.get_project(project_id)
    if project is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "project_not_found",
            "Project was not found.",
        )
    return project


def _load_state(
    audit_repository: AuditRepository,
    state_repository: ProcedureStateRepository,
    project_id: str,
    state_id: str,
    request: Request,
) -> dict[str, Any]:
    _load_project(audit_repository, project_id, request)
    state_row = state_repository.get_procedure_state(project_id, state_id)
    if state_row is None:
        raise _state_not_found(request)
    return state_row


def _state_not_found(request: Request) -> HTTPException:
    return _error(
        status.HTTP_404_NOT_FOUND,
        request,
        "procedure_state_not_found",
        "Procedure execution state was not found.",
    )


def _validate_transition_or_raise(
    *,
    request: Request,
    from_status: str,
    to_status: str,
    source_type: str,
    reason: str,
    abstention_level: str | None,
    related_evidence_ids: list[str],
) -> None:
    try:
        validate_transition(
            from_status=from_status,  # type: ignore[arg-type]
            to_status=to_status,  # type: ignore[arg-type]
            source_type=source_type,  # type: ignore[arg-type]
            reason=reason,
            abstention_level=abstention_level,
            related_evidence_ids=related_evidence_ids,
        )
    except ProcedureStateMachineError as error:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            request,
            "invalid_procedure_state_transition",
            str(error),
        ) from error


def _validate_related_evidence(
    repository: AuditRepository,
    project_id: str,
    evidence_ids: list[str],
    request: Request,
) -> None:
    for evidence_id in evidence_ids:
        if repository.get_evidence(project_id, evidence_id) is None:
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                request,
                "evidence_not_found",
                f"Evidence {evidence_id} was not found for this project.",
            )
