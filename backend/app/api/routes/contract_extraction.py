from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.capabilities.contract_extraction import (
    EXTRACTOR_VERSION,
    build_contract_evidence_value,
    extract_contract_fields,
    extraction_summary,
    fields_for_unavailable_document,
)
from app.core.config import get_settings
from app.schemas.contract_extraction import (
    ContractExtractionListResponse,
    ContractExtractionRequest,
    ContractExtractionResponse,
    ContractFieldExtraction,
)
from app.schemas.error import ErrorResponse
from app.services.repository import AuditRepository

router = APIRouter(
    prefix="/projects/{project_id}/documents/{document_id}/contract-extraction",
    tags=["contract-extraction"],
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

    repository = AuditRepository(get_settings())
    _load_document(repository, project_id, document_id, request)
    chunks = repository.list_document_chunks(project_id, document_id)
    if not chunks:
        fields, extraction_status, node_status, failure_reason = _unavailable_fields(
            repository,
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

    run = repository.create_contract_extraction_run(
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
    repository = AuditRepository(get_settings())
    _load_document(repository, project_id, document_id, request)
    trace_id = _trace_id(request)
    items = [
        ContractExtractionResponse(**row, trace_id=trace_id)
        for row in repository.list_contract_extraction_runs(project_id, document_id)
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
    repository: AuditRepository,
    project_id: str,
    document_id: str,
) -> tuple[list[ContractFieldExtraction], str, str, str]:
    parse_runs = repository.list_document_parse_runs(project_id, document_id)
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
