from fastapi import APIRouter, HTTPException, Request, status

from app.orchestrator.procedure_registry import (
    evaluate_readiness,
    get_procedure,
    list_procedures,
)
from app.schemas.error import ErrorResponse
from app.schemas.procedure_registry import (
    ProcedureReadinessRequest,
    ProcedureReadinessResponse,
    ProcedureRegistryListResponse,
    ProcedureRegistryResponse,
)

router = APIRouter(prefix="/procedure-registry", tags=["procedure-registry"])


def _trace_id(request: Request) -> str:
    return request.state.trace_id


def _not_found(request: Request, procedure_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ErrorResponse(
            code="procedure_not_found",
            message=f"Procedure {procedure_id} was not found.",
            trace_id=_trace_id(request),
        ).model_dump(),
    )


@router.get(
    "",
    response_model=ProcedureRegistryListResponse,
    summary="List registered audit procedures",
)
async def list_procedure_registry(request: Request) -> ProcedureRegistryListResponse:
    procedures = list_procedures()
    return ProcedureRegistryListResponse(
        items=procedures,
        total=len(procedures),
        trace_id=_trace_id(request),
    )


@router.get(
    "/{procedure_id}",
    response_model=ProcedureRegistryResponse,
    summary="Get one registered audit procedure",
)
async def get_registered_procedure(
    procedure_id: str,
    request: Request,
) -> ProcedureRegistryResponse:
    procedure = get_procedure(procedure_id)
    if procedure is None:
        raise _not_found(request, procedure_id)
    return ProcedureRegistryResponse(procedure=procedure, trace_id=_trace_id(request))


@router.post(
    "/{procedure_id}/readiness",
    response_model=ProcedureReadinessResponse,
    summary="Explain procedure readiness from available inputs",
)
async def explain_procedure_readiness(
    procedure_id: str,
    payload: ProcedureReadinessRequest,
    request: Request,
) -> ProcedureReadinessResponse:
    procedure = get_procedure(procedure_id)
    if procedure is None:
        raise _not_found(request, procedure_id)
    readiness = evaluate_readiness(
        procedure=procedure,
        available_inputs=payload.available_inputs,
        completed_procedures=payload.completed_procedures,
        mark_not_applicable=payload.mark_not_applicable,
        not_applicable_reason=payload.not_applicable_reason,
    )
    return readiness.model_copy(update={"trace_id": _trace_id(request)})
