from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import get_settings
from app.schemas.normalization import (
    DatasetQualityCreate,
    DatasetQualityListResponse,
    DatasetQualityResponse,
    NormalizedValueCreate,
    NormalizedValueListResponse,
    NormalizedValueResponse,
)
from app.services.normalization import assess_dataset_quality, normalize_value
from app.services.repository import AuditRepository

router = APIRouter(prefix="/projects/{project_id}/normalization", tags=["normalization"])


@router.post(
    "/values",
    response_model=NormalizedValueResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_normalized_value(
    project_id: str,
    payload: NormalizedValueCreate,
    request: Request,
) -> dict:
    repository = AuditRepository(get_settings())
    _ensure_project_exists(repository, project_id)
    _ensure_related_objects_exist(repository, project_id, payload)
    normalized = normalize_value(
        value_type=payload.value_type,
        raw_value=payload.raw_value,
        normalization_rule=payload.normalization_rule,
    )
    item = repository.create_normalized_value(
        project_id=project_id,
        evidence_id=payload.evidence_id,
        document_id=payload.document_id,
        procedure_id=payload.procedure_id,
        field_name=payload.field_name,
        value_type=payload.value_type,
        raw_value=payload.raw_value,
        standard_value=normalized.standard_value,
        normalization_rule=normalized.normalization_rule,
        quality_status=normalized.quality_status,
        quality_score=normalized.quality_score,
        issues=normalized.issues,
    )
    item["trace_id"] = request.state.trace_id
    return item


@router.get("/values", response_model=NormalizedValueListResponse)
def list_normalized_values(
    project_id: str,
    request: Request,
) -> dict:
    repository = AuditRepository(get_settings())
    _ensure_project_exists(repository, project_id)
    items = repository.list_normalized_values(project_id)
    for item in items:
        item["trace_id"] = request.state.trace_id
    return {"items": items, "total": len(items)}


@router.post(
    "/datasets/quality",
    response_model=DatasetQualityResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_quality(
    project_id: str,
    payload: DatasetQualityCreate,
    request: Request,
) -> dict:
    repository = AuditRepository(get_settings())
    _ensure_project_exists(repository, project_id)
    result = assess_dataset_quality(
        total_records=payload.total_records,
        usable_records=payload.usable_records,
        partial_records=payload.partial_records,
        rejected_records=payload.rejected_records,
        issues=payload.issues,
    )
    item = repository.create_dataset_quality(
        project_id=project_id,
        dataset_name=payload.dataset_name,
        total_records=payload.total_records,
        usable_records=payload.usable_records,
        partial_records=payload.partial_records,
        rejected_records=payload.rejected_records,
        quality_score=result.quality_score,
        quality_status=result.quality_status,
        procedure_readiness=result.procedure_readiness,
        issues=result.issues,
    )
    item["trace_id"] = request.state.trace_id
    return item


@router.get("/datasets/quality", response_model=DatasetQualityListResponse)
def list_dataset_quality(
    project_id: str,
    request: Request,
) -> dict:
    repository = AuditRepository(get_settings())
    _ensure_project_exists(repository, project_id)
    items = repository.list_dataset_quality(project_id)
    for item in items:
        item["trace_id"] = request.state.trace_id
    return {"items": items, "total": len(items)}


def _ensure_project_exists(repository: AuditRepository, project_id: str) -> None:
    if repository.get_project(project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "project_not_found", "message": "Project was not found."},
        )


def _ensure_related_objects_exist(
    repository: AuditRepository,
    project_id: str,
    payload: NormalizedValueCreate,
) -> None:
    if payload.document_id and repository.get_document(project_id, payload.document_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "document_not_found", "message": "Document was not found."},
        )
    if payload.procedure_id and repository.get_procedure(project_id, payload.procedure_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "procedure_not_found", "message": "Procedure was not found."},
        )
    if payload.evidence_id and repository.get_evidence(project_id, payload.evidence_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "evidence_not_found", "message": "Evidence was not found."},
        )
