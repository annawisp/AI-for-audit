import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status

from app.capabilities.contract_extraction import (
    EXTRACTOR_VERSION,
    build_contract_evidence_value,
    extract_contract_fields,
    extraction_summary,
    fields_for_unavailable_document,
)
from app.core.config import Settings, get_settings
from app.core.database import get_connection
from app.schemas.contract_extraction import (
    ContractExtractionListResponse,
    ContractExtractionRequest,
    ContractExtractionResponse,
    ContractFieldExtraction,
)
from app.schemas.error import ErrorResponse
from app.services.repository import AuditRepository, utc_now

router = APIRouter(
    prefix="/projects/{project_id}/documents/{document_id}/contract-extraction",
    tags=["contract-extraction"],
)


def _trace_id(request: Request) -> str:
    return request.state.trace_id


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _error(status_code: int, request: Request, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(code=code, message=message, trace_id=_trace_id(request)).model_dump(),
    )


@router.post(
    "",
    response_model=ContractExtractionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Extract revenue-audit contract fields and create evidence",
)
def create_contract_extraction(
    project_id: str,
    document_id: str,
    payload: ContractExtractionRequest,
    request: Request,
) -> ContractExtractionResponse:
    if payload.extractor_type != "rule_based":
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            request,
            "extractor_not_available",
            "Only rule_based extractor is available in TASK-302.",
        )

    settings = get_settings()
    _ensure_contract_extraction_tables(settings)
    repository = AuditRepository(settings)
    _load_document(repository, project_id, document_id, request)
    chunks = _list_document_chunks(settings, project_id, document_id)
    if not chunks:
        fields, extraction_status, node_status, failure_reason = _unavailable_fields(
            settings,
            project_id,
            document_id,
        )
        evidence = None
    else:
        fields = extract_contract_fields(chunks)
        extraction_status, node_status, confidence_level = extraction_summary(fields)
        failure_reason = None
        evidence = repository.create_evidence(
            project_id=project_id,
            procedure_id=None,
            document_id=document_id,
            source="capability:contract_extraction",
            extracted_value=build_contract_evidence_value(
                document_id=document_id,
                fields=fields,
                extractor_type=payload.extractor_type,
            ),
            conclusion=_conclusion(fields),
            execution_status="completed",
            node_status=node_status,
            judgment_status=(
                "PENDING_REVIEW" if extraction_status == "REQUIRES_REVIEW" else "AI_GENERATED"
            ),
            confidence=None,
            model_confidence=None,
            confidence_level=confidence_level,
            confidence_basis="Rule-based contract field extraction from TASK-301 document chunks.",
            reviewer=None,
        )

    run = _create_contract_extraction_run(
        settings=settings,
        project_id=project_id,
        document_id=document_id,
        evidence_id=evidence["evidence_id"] if evidence else None,
        status=extraction_status,
        extractor_type=payload.extractor_type,
        extractor_version=EXTRACTOR_VERSION,
        fields=[field.model_dump() for field in fields],
        failure_reason=failure_reason,
    )
    return ContractExtractionResponse(
        **{
            **run,
            "fields": fields,
            "trace_id": _trace_id(request),
        }
    )


@router.get(
    "",
    response_model=ContractExtractionListResponse,
    summary="List contract extraction runs",
)
def list_contract_extractions(
    project_id: str,
    document_id: str,
    request: Request,
) -> ContractExtractionListResponse:
    settings = get_settings()
    _ensure_contract_extraction_tables(settings)
    repository = AuditRepository(settings)
    _load_document(repository, project_id, document_id, request)
    trace_id = _trace_id(request)
    items = [
        ContractExtractionResponse(**row, trace_id=trace_id)
        for row in _list_contract_extraction_runs(settings, project_id, document_id)
    ]
    return ContractExtractionListResponse(items=items, total=len(items))


def _load_document(
    repository: AuditRepository,
    project_id: str,
    document_id: str,
    request: Request,
) -> dict[str, Any]:
    if repository.get_project(project_id) is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "project_not_found",
            "Project was not found.",
        )
    document = repository.get_document(project_id, document_id)
    if document is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "document_not_found",
            "Document was not found.",
        )
    return document


def _unavailable_fields(
    settings: Settings,
    project_id: str,
    document_id: str,
) -> tuple[list[ContractFieldExtraction], str, str, str]:
    parse_runs = _list_document_parse_runs(settings, project_id, document_id)
    if parse_runs and parse_runs[0]["status"] == "OCR_REQUIRED":
        return (
            fields_for_unavailable_document("DOCUMENT_REQUIRES_OCR"),
            "BLOCKED",
            "blocked",
            "document_requires_ocr",
        )
    return (
        fields_for_unavailable_document("DOCUMENT_NOT_PARSED"),
        "BLOCKED",
        "blocked",
        "document_not_parsed",
    )


def _conclusion(fields: list[ContractFieldExtraction]) -> str:
    extracted_count = sum(1 for field in fields if field.status == "EXTRACTED")
    not_applicable_count = sum(1 for field in fields if field.status == "NOT_APPLICABLE")
    conflict_count = sum(1 for field in fields if field.status == "CONFLICTING_EVIDENCE")
    missing_count = sum(1 for field in fields if field.status == "MISSING_IN_DOCUMENT")
    return (
        f"Contract extraction completed: {extracted_count} field(s) extracted, "
        f"{not_applicable_count} not applicable, {conflict_count} conflicting, "
        f"{missing_count} missing in document."
    )


def _parse_run_row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["requires_ocr"] = bool(item["requires_ocr"])
    item["ocr_requested"] = bool(item["ocr_requested"])
    return item


def _document_chunk_row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["content"] = json.loads(str(item.pop("content_json")))
    return item


def _contract_extraction_run_row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["fields"] = json.loads(str(item.pop("fields_json")))
    return item


def _ensure_contract_extraction_tables(settings: Settings) -> None:
    with get_connection(settings) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS document_parse_runs (
                parse_run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                status TEXT NOT NULL,
                parser_name TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                requires_ocr INTEGER NOT NULL,
                ocr_requested INTEGER NOT NULL,
                ocr_status TEXT NOT NULL,
                failure_reason TEXT,
                chunks_count INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(project_id),
                FOREIGN KEY (document_id) REFERENCES documents(document_id)
            );

            CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id TEXT PRIMARY KEY,
                parse_run_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                chunk_type TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                text TEXT NOT NULL,
                content_json TEXT NOT NULL,
                page_number INTEGER,
                sheet_name TEXT,
                row_number INTEGER,
                paragraph_number INTEGER,
                table_index INTEGER,
                source_locator TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (parse_run_id) REFERENCES document_parse_runs(parse_run_id),
                FOREIGN KEY (project_id) REFERENCES projects(project_id),
                FOREIGN KEY (document_id) REFERENCES documents(document_id)
            );

            CREATE TABLE IF NOT EXISTS contract_extraction_runs (
                extraction_run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                evidence_id TEXT,
                status TEXT NOT NULL,
                extractor_type TEXT NOT NULL,
                extractor_version TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                failure_reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(project_id),
                FOREIGN KEY (document_id) REFERENCES documents(document_id),
                FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
            );
            """
        )


def _list_document_parse_runs(
    settings: Settings,
    project_id: str,
    document_id: str,
) -> list[dict[str, Any]]:
    with get_connection(settings) as connection:
        rows = connection.execute(
            """
            SELECT * FROM document_parse_runs
            WHERE project_id = ? AND document_id = ?
            ORDER BY started_at DESC
            """,
            (project_id, document_id),
        ).fetchall()
    return [item for row in rows if (item := _parse_run_row_to_dict(row)) is not None]


def _list_document_chunks(
    settings: Settings,
    project_id: str,
    document_id: str,
) -> list[dict[str, Any]]:
    with get_connection(settings) as connection:
        rows = connection.execute(
            """
            SELECT * FROM document_chunks
            WHERE project_id = ? AND document_id = ?
            ORDER BY created_at DESC, sequence_number ASC
            """,
            (project_id, document_id),
        ).fetchall()
    return [item for row in rows if (item := _document_chunk_row_to_dict(row)) is not None]


def _create_contract_extraction_run(
    *,
    settings: Settings,
    project_id: str,
    document_id: str,
    evidence_id: str | None,
    status: str,
    extractor_type: str,
    extractor_version: str,
    fields: list[dict[str, Any]],
    failure_reason: str | None,
) -> dict[str, Any]:
    extraction_run_id = f"cex_{uuid4().hex}"
    now = utc_now()
    with get_connection(settings) as connection:
        connection.execute(
            """
            INSERT INTO contract_extraction_runs (
                extraction_run_id, project_id, document_id, evidence_id, status,
                extractor_type, extractor_version, fields_json, failure_reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                extraction_run_id,
                project_id,
                document_id,
                evidence_id,
                status,
                extractor_type,
                extractor_version,
                _json_dumps(fields),
                failure_reason,
                now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM contract_extraction_runs WHERE extraction_run_id = ?",
            (extraction_run_id,),
        ).fetchone()
    result = _contract_extraction_run_row_to_dict(row)
    if result is None:
        raise RuntimeError("Contract extraction run was not persisted.")
    return result


def _list_contract_extraction_runs(
    settings: Settings,
    project_id: str,
    document_id: str,
) -> list[dict[str, Any]]:
    with get_connection(settings) as connection:
        rows = connection.execute(
            """
            SELECT * FROM contract_extraction_runs
            WHERE project_id = ? AND document_id = ?
            ORDER BY created_at DESC
            """,
            (project_id, document_id),
        ).fetchall()
    return [
        item for row in rows if (item := _contract_extraction_run_row_to_dict(row)) is not None
    ]
