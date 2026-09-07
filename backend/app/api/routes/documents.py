from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from app.core.config import get_settings
from app.schemas.document import DocumentListResponse, DocumentResponse
from app.schemas.error import ErrorResponse
from app.services.repository import AuditRepository
from app.services.storage import UploadValidationError, save_upload_file

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])


def _trace_id(request: Request) -> str:
    return request.state.trace_id


def _document_response(row: dict[str, Any], trace_id: str) -> DocumentResponse:
    return DocumentResponse(**row, trace_id=trace_id)


def _error(status_code: int, request: Request, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(code=code, message=message, trace_id=_trace_id(request)).model_dump(),
    )


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a project document",
)
async def upload_document(
    project_id: str,
    request: Request,
    file: Annotated[UploadFile, File(...)],
) -> DocumentResponse:
    settings = get_settings()
    repository = AuditRepository(settings)
    if repository.get_project(project_id) is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "project_not_found",
            "Project was not found",
        )

    try:
        stored_file = await save_upload_file(
            project_id=project_id,
            upload_file=file,
            settings=settings,
        )
    except UploadValidationError as error:
        raise _error(status.HTTP_400_BAD_REQUEST, request, error.code, str(error)) from error

    document = repository.create_document(
        document_id=str(stored_file["document_id"]),
        project_id=project_id,
        original_filename=str(stored_file["original_filename"]),
        stored_filename=str(stored_file["stored_filename"]),
        content_type=file.content_type,
        size_bytes=int(stored_file["size_bytes"]),
        checksum_sha256=str(stored_file["checksum_sha256"]),
        storage_path=str(stored_file["storage_path"]),
    )
    return _document_response(document, _trace_id(request))


@router.get("", response_model=DocumentListResponse, summary="List project documents")
def list_documents(project_id: str, request: Request) -> DocumentListResponse:
    repository = AuditRepository(get_settings())
    if repository.get_project(project_id) is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "project_not_found",
            "Project was not found",
        )
    return DocumentListResponse(
        items=[
            _document_response(row, _trace_id(request))
            for row in repository.list_documents(project_id)
        ],
        trace_id=_trace_id(request),
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get project document metadata",
)
def get_document(project_id: str, document_id: str, request: Request) -> DocumentResponse:
    repository = AuditRepository(get_settings())
    document = repository.get_document(project_id, document_id)
    if document is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            request,
            "document_not_found",
            "Document was not found",
        )
    return _document_response(document, _trace_id(request))
