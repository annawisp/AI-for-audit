from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.capabilities.data_reconciliation import (
    RULES_VERSION,
    build_data_reconciliation_evidence_value,
    run_data_reconciliation,
)
from app.core.config import get_settings
from app.schemas.data_reconciliation import (
    DataReconciliationListResponse,
    DataReconciliationRequest,
    DataReconciliationResponse,
)
from app.schemas.error import ErrorResponse
from app.services.repository import AuditRepository

router = APIRouter(
    prefix="/projects/{project_id}/data-reconciliation",
    tags=["data-reconciliation"],
)


def _trace_id(request: Request) -> str:
    return request.state.trace_id


def _error(status_code: int, request: Request, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(code=code, message=message, trace_id=_trace_id(request)).model_dump(),
    )


@router.post(
    "",
    response_model=DataReconciliationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run data reconciliation and exception screening",
)
def create_data_reconciliation(
    project_id: str,
    payload: DataReconciliationRequest,
    request: Request,
) -> DataReconciliationResponse:
    repository = AuditRepository(get_settings())
    project = _load_project(repository, project_id, request)
    contract_evidence = _load_optional_evidence(
        repository,
        project_id,
        payload.contract_evidence_id,
        "capability:contract_extraction",
        "invalid_contract_evidence_source",
        request,
    )
    recognition_evidence = _load_optional_evidence(
        repository,
        project_id,
        payload.revenue_recognition_evidence_id,
        "capability:revenue_recognition_analysis",
        "invalid_revenue_recognition_evidence_source",
        request,
    )
    risk_evidence = _load_optional_evidence(
        repository,
        project_id,
        payload.revenue_risk_evidence_id,
        "capability:revenue_risk_identification",
        "invalid_revenue_risk_evidence_source",
        request,
    )
    _ensure_same_document(request, contract_evidence, recognition_evidence, risk_evidence)
    result = run_data_reconciliation(
        project=project,
        contract_evidence=contract_evidence,
        revenue_recognition_evidence=recognition_evidence,
        revenue_risk_evidence=risk_evidence,
        revenue_records=payload.revenue_records,
        receivable_records=payload.receivable_records,
        cash_receipt_records=payload.cash_receipt_records,
        audit_period_start=payload.audit_period_start,
        audit_period_end=payload.audit_period_end,
    )
    evidence = repository.create_evidence(
        project_id=project_id,
        procedure_id=None,
        document_id=_document_id(contract_evidence, recognition_evidence, risk_evidence),
        source="capability:data_reconciliation_anomaly_detection",
        extracted_value=build_data_reconciliation_evidence_value(result),
        conclusion=result.conclusion,
        execution_status="completed",
        node_status=result.node_status,
        judgment_status=result.judgment_status,
        confidence=None,
        model_confidence=None,
        confidence_level=result.confidence_level,
        confidence_basis="Rule-based data reconciliation and anomaly screening.",
        reviewer=None,
    )
    run = repository.create_data_reconciliation_run(
        project_id=project_id,
        contract_evidence_id=payload.contract_evidence_id,
        revenue_recognition_evidence_id=payload.revenue_recognition_evidence_id,
        revenue_risk_evidence_id=payload.revenue_risk_evidence_id,
        evidence_id=evidence["evidence_id"],
        status=result.status,
        overall_exception_level=result.overall_exception_level,
        coverage=result.coverage.model_dump(),
        nodes=[node.model_dump() for node in result.nodes],
        matched_links=[link.model_dump() for link in result.matched_links],
        exceptions=[exception.model_dump() for exception in result.exceptions],
        limitations=result.limitations,
        source_evidence_ids=result.source_evidence_ids,
        engine_type=payload.engine_type,
        rules_version=RULES_VERSION,
        conclusion=result.conclusion,
    )
    return DataReconciliationResponse(
        **{
            **run,
            "coverage": result.coverage,
            "coverage_ratio": result.coverage.coverage_ratio,
            "nodes": result.nodes,
            "matched_links": result.matched_links,
            "exceptions": result.exceptions,
            "limitations": result.limitations,
            "trace_id": _trace_id(request),
        }
    )


@router.get(
    "",
    response_model=DataReconciliationListResponse,
    summary="List data reconciliation runs",
)
def list_data_reconciliations(
    project_id: str,
    request: Request,
) -> DataReconciliationListResponse:
    repository = AuditRepository(get_settings())
    _load_project(repository, project_id, request)
    trace_id = _trace_id(request)
    items = [
        DataReconciliationResponse(**row, trace_id=trace_id)
        for row in repository.list_data_reconciliation_runs(project_id)
    ]
    return DataReconciliationListResponse(items=items, total=len(items))


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


def _load_optional_evidence(
    repository: AuditRepository,
    project_id: str,
    evidence_id: str | None,
    expected_source: str,
    invalid_code: str,
    request: Request,
) -> dict[str, Any] | None:
    if evidence_id is None:
        return None
    evidence = repository.get_evidence(project_id, evidence_id)
    if evidence is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "evidence_not_found",
            "Evidence was not found.",
        )
    if evidence["source"] != expected_source:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            request,
            invalid_code,
            f"TASK-305 requires {expected_source} evidence for this field.",
        )
    if evidence["judgment_status"] == "REJECTED":
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            request,
            "rejected_evidence_not_allowed",
            "Rejected evidence cannot be used as downstream input.",
        )
    return evidence


def _document_id(*evidence_items: dict[str, Any] | None) -> str | None:
    for evidence in evidence_items:
        if evidence and evidence.get("document_id"):
            return str(evidence["document_id"])
    return None


def _ensure_same_document(
    request: Request,
    *evidence_items: dict[str, Any] | None,
) -> None:
    document_ids = {
        str(evidence["document_id"])
        for evidence in evidence_items
        if evidence and evidence.get("document_id")
    }
    if len(document_ids) > 1:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            request,
            "evidence_document_mismatch",
            "Upstream evidence items must refer to the same document.",
        )
