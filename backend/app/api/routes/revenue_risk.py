from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.capabilities.revenue_risk import build_revenue_risk_evidence_value, identify_revenue_risks
from app.core.config import get_settings
from app.schemas.error import ErrorResponse
from app.schemas.revenue_risk import RevenueRiskListResponse, RevenueRiskRequest, RevenueRiskResponse
from app.services.repository import AuditRepository

router = APIRouter(prefix="/projects/{project_id}/revenue-risk", tags=["revenue-risk"])
SOURCE = "capability:revenue_risk_identification"


def _trace_id(request: Request) -> str:
    return request.state.trace_id


def _error(status_code: int, request: Request, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=ErrorResponse(code=code, message=message, trace_id=_trace_id(request)).model_dump())


@router.post("", response_model=RevenueRiskResponse, status_code=status.HTTP_201_CREATED)
def create_revenue_risk(project_id: str, payload: RevenueRiskRequest, request: Request) -> RevenueRiskResponse:
    repository = AuditRepository(get_settings())
    project = _load_project(repository, project_id, request)
    contract_evidence = _load_optional_evidence(repository, project_id, payload.contract_evidence_id, "capability:contract_extraction", "invalid_contract_evidence_source", request)
    recognition_evidence = _load_optional_evidence(repository, project_id, payload.revenue_recognition_evidence_id, "capability:revenue_recognition_analysis", "invalid_revenue_recognition_evidence_source", request)
    result = identify_revenue_risks(project=project, contract_evidence=contract_evidence, revenue_recognition_evidence=recognition_evidence, revenue_records=payload.revenue_records, enable_semantic_judgment=payload.enable_semantic_judgment)
    evidence = repository.create_evidence(
        project_id=project_id,
        procedure_id=None,
        document_id=_document_id(contract_evidence, recognition_evidence),
        source=SOURCE,
        extracted_value=build_revenue_risk_evidence_value(result),
        conclusion=result["conclusion"],
        execution_status="completed",
        node_status=result["node_status"],
        judgment_status=result["judgment_status"],
        confidence=None,
        model_confidence=None,
        confidence_level=result["confidence_level"],
        confidence_basis="Rule-based TASK-304 revenue risk identification.",
        reviewer=None,
    )
    return _response_from_result(project_id, evidence["evidence_id"], result, request)


@router.get("", response_model=RevenueRiskListResponse)
def list_revenue_risks(project_id: str, request: Request) -> RevenueRiskListResponse:
    repository = AuditRepository(get_settings())
    _load_project(repository, project_id, request)
    items = []
    for evidence in repository.list_evidence(project_id):
        if evidence["source"] != SOURCE:
            continue
        value = evidence["extracted_value"]
        result = {
            "status": value["status"],
            "overall_risk_level": value["overall_risk_level"],
            "coverage": value["coverage"],
            "risk_signals": value["risk_signals"],
            "limitations": value["limitations"],
            "source_evidence_ids": value.get("source_evidence_ids", []),
            "rules_version": value["rules_version"],
            "engine_type": "rule_based",
            "llm_judgment_status": "NOT_RECORDED",
            "conclusion": value["conclusion"],
        }
        items.append(_response_from_result(project_id, evidence["evidence_id"], result, request))
    return RevenueRiskListResponse(items=items, total=len(items))


def _response_from_result(project_id: str, evidence_id: str, result: dict[str, Any], request: Request) -> RevenueRiskResponse:
    coverage = result["coverage"]
    return RevenueRiskResponse(
        run_id=evidence_id,
        project_id=project_id,
        evidence_id=evidence_id,
        status=result["status"],
        overall_risk_level=result["overall_risk_level"],
        coverage=coverage,
        coverage_ratio=coverage["coverage_ratio"],
        rule_coverage_ratio=coverage["rule_coverage_ratio"],
        semantic_judgment_coverage=coverage["semantic_judgment_coverage"],
        risk_signals=result["risk_signals"],
        limitations=result["limitations"],
        conclusion=result["conclusion"],
        source_evidence_ids=result["source_evidence_ids"],
        engine_type=result.get("engine_type", "rule_based"),
        rules_version=result["rules_version"],
        llm_judgment_status=result["llm_judgment_status"],
        trace_id=_trace_id(request),
    )


def _load_project(repository: AuditRepository, project_id: str, request: Request) -> dict[str, Any]:
    project = repository.get_project(project_id)
    if project is None:
        raise _error(status.HTTP_404_NOT_FOUND, request, "project_not_found", "Project was not found.")
    return project


def _load_optional_evidence(repository: AuditRepository, project_id: str, evidence_id: str | None, expected_source: str, invalid_code: str, request: Request) -> dict[str, Any] | None:
    if evidence_id is None:
        return None
    evidence = repository.get_evidence(project_id, evidence_id)
    if evidence is None:
        raise _error(status.HTTP_404_NOT_FOUND, request, "evidence_not_found", "Evidence was not found.")
    if evidence["source"] != expected_source:
        raise _error(status.HTTP_400_BAD_REQUEST, request, invalid_code, f"TASK-304 requires {expected_source} evidence for this field.")
    return evidence


def _document_id(*evidence_items: dict[str, Any] | None) -> str | None:
    for evidence in evidence_items:
        if evidence and evidence.get("document_id"):
            return str(evidence["document_id"])
    return None
