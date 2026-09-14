import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status

from app.capabilities.revenue_recognition import (
    ANALYZER_VERSION,
    analyze_revenue_recognition,
    build_revenue_recognition_evidence_value,
)
from app.core.config import Settings, get_settings
from app.core.database import get_connection
from app.schemas.error import ErrorResponse
from app.schemas.revenue_recognition import (
    RevenueRecognitionListResponse,
    RevenueRecognitionRequest,
    RevenueRecognitionResponse,
)
from app.services.repository import AuditRepository, utc_now

router = APIRouter(
    prefix="/projects/{project_id}/revenue-recognition",
    tags=["revenue-recognition"],
)


def _trace_id(request: Request) -> str:
    return request.state.trace_id


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _error(status_code: int, request: Request, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(code=code, message=message, trace_id=_trace_id(request)).model_dump(),
    )


@router.post(
    "",
    response_model=RevenueRecognitionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Analyze revenue recognition from contract extraction evidence",
)
def create_revenue_recognition(
    project_id: str,
    payload: RevenueRecognitionRequest,
    request: Request,
) -> RevenueRecognitionResponse:
    if payload.analyzer_type != "rule_based":
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            request,
            "analyzer_not_available",
            "Only rule_based analyzer is available in TASK-303.",
        )

    settings = get_settings()
    _ensure_revenue_recognition_tables(settings)
    repository = AuditRepository(settings)
    project = _load_project(repository, project_id, request)
    contract_evidence = _load_contract_evidence(
        repository,
        project_id,
        payload.contract_evidence_id,
        request,
    )
    result = analyze_revenue_recognition(
        contract_evidence=contract_evidence,
        project=project,
        revenue_records=payload.revenue_records,
    )
    evidence = None
    if result.status != "BLOCKED":
        evidence = repository.create_evidence(
            project_id=project_id,
            procedure_id=None,
            document_id=contract_evidence.get("document_id"),
            source="capability:revenue_recognition_analysis",
            extracted_value=build_revenue_recognition_evidence_value(
                contract_evidence_id=payload.contract_evidence_id,
                coverage=result.coverage,
                nodes=result.nodes,
                limitations=result.limitations,
                impact=result.impact,
                analyzer_type=payload.analyzer_type,
            ),
            conclusion=result.conclusion,
            execution_status="completed",
            node_status=result.node_status,
            judgment_status=result.judgment_status,
            confidence=None,
            model_confidence=None,
            confidence_level=result.confidence_level,
            confidence_basis=(
                "Rule-based revenue recognition analysis from TASK-302 contract evidence."
            ),
            reviewer=None,
        )
    run = _create_revenue_recognition_run(
        settings=settings,
        project_id=project_id,
        contract_evidence_id=payload.contract_evidence_id,
        evidence_id=evidence["evidence_id"] if evidence else None,
        status=result.status,
        analyzer_type=payload.analyzer_type,
        analyzer_version=ANALYZER_VERSION,
        coverage=result.coverage.model_dump(),
        nodes=[node.model_dump() for node in result.nodes],
        limitations=result.limitations,
        impact=result.impact,
        conclusion=result.conclusion,
        failure_reason=result.failure_reason,
    )
    return RevenueRecognitionResponse(
        **{
            **run,
            "coverage": result.coverage,
            "nodes": result.nodes,
            "limitations": result.limitations,
            "trace_id": _trace_id(request),
        }
    )


@router.get(
    "",
    response_model=RevenueRecognitionListResponse,
    summary="List revenue recognition analysis runs",
)
def list_revenue_recognitions(
    project_id: str,
    request: Request,
) -> RevenueRecognitionListResponse:
    settings = get_settings()
    _ensure_revenue_recognition_tables(settings)
    repository = AuditRepository(settings)
    _load_project(repository, project_id, request)
    trace_id = _trace_id(request)
    items = [
        RevenueRecognitionResponse(**row, trace_id=trace_id)
        for row in _list_revenue_recognition_runs(settings, project_id)
    ]
    return RevenueRecognitionListResponse(items=items, total=len(items))


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


def _load_contract_evidence(
    repository: AuditRepository,
    project_id: str,
    evidence_id: str,
    request: Request,
) -> dict[str, Any]:
    evidence = repository.get_evidence(project_id, evidence_id)
    if evidence is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "contract_evidence_not_found",
            "Contract extraction evidence was not found.",
        )
    if evidence["source"] != "capability:contract_extraction":
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            request,
            "invalid_contract_evidence_source",
            "TASK-303 requires TASK-302 contract extraction evidence.",
        )
    return evidence


def _revenue_recognition_run_row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["coverage"] = json.loads(str(item.pop("coverage_json")))
    item["nodes"] = json.loads(str(item.pop("nodes_json")))
    item["limitations"] = json.loads(str(item.pop("limitations_json")))
    return item


def _ensure_revenue_recognition_tables(settings: Settings) -> None:
    with get_connection(settings) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS revenue_recognition_runs (
                recognition_run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                contract_evidence_id TEXT NOT NULL,
                evidence_id TEXT,
                status TEXT NOT NULL,
                analyzer_type TEXT NOT NULL,
                analyzer_version TEXT NOT NULL,
                coverage_json TEXT NOT NULL,
                nodes_json TEXT NOT NULL,
                limitations_json TEXT NOT NULL,
                impact TEXT NOT NULL,
                conclusion TEXT,
                failure_reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(project_id),
                FOREIGN KEY (contract_evidence_id) REFERENCES evidence(evidence_id),
                FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
            )
            """
        )


def _create_revenue_recognition_run(
    *,
    settings: Settings,
    project_id: str,
    contract_evidence_id: str,
    evidence_id: str | None,
    status: str,
    analyzer_type: str,
    analyzer_version: str,
    coverage: dict[str, Any],
    nodes: list[dict[str, Any]],
    limitations: list[str],
    impact: str,
    conclusion: str | None,
    failure_reason: str | None,
) -> dict[str, Any]:
    recognition_run_id = str(uuid4())
    timestamp = utc_now()
    with get_connection(settings) as connection:
        connection.execute(
            """
            INSERT INTO revenue_recognition_runs (
                recognition_run_id, project_id, contract_evidence_id, evidence_id,
                status, analyzer_type, analyzer_version, coverage_json,
                nodes_json, limitations_json, impact, conclusion, failure_reason,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recognition_run_id,
                project_id,
                contract_evidence_id,
                evidence_id,
                status,
                analyzer_type,
                analyzer_version,
                _json_dumps(coverage),
                _json_dumps(nodes),
                _json_dumps(limitations),
                impact,
                conclusion,
                failure_reason,
                timestamp,
            ),
        )
        row = connection.execute(
            """
            SELECT * FROM revenue_recognition_runs
            WHERE project_id = ? AND recognition_run_id = ?
            """,
            (project_id, recognition_run_id),
        ).fetchone()
    item = _revenue_recognition_run_row_to_dict(row)
    if item is None:
        raise RuntimeError("Created revenue recognition run could not be loaded")
    return item


def _list_revenue_recognition_runs(settings: Settings, project_id: str) -> list[dict[str, Any]]:
    with get_connection(settings) as connection:
        rows = connection.execute(
            """
            SELECT * FROM revenue_recognition_runs
            WHERE project_id = ?
            ORDER BY created_at DESC
            """,
            (project_id,),
        ).fetchall()
    return [
        item for row in rows if (item := _revenue_recognition_run_row_to_dict(row)) is not None
    ]
