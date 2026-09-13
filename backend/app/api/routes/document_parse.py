import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import get_settings
from app.core.database import get_connection
from app.schemas.document_parse import (
    DocumentChunkListResponse,
    DocumentChunkResponse,
    DocumentParseRequest,
    DocumentParseRunListResponse,
    DocumentParseRunResponse,
)
from app.schemas.error import ErrorResponse
from app.services.document_parser import ParsedChunk, parse_document
from app.services.repository import AuditRepository, utc_now

router = APIRouter(
    prefix="/projects/{project_id}/documents/{document_id}",
    tags=["document-parsing"],
)


def _trace_id(request: Request) -> str:
    return request.state.trace_id


def _error(status_code: int, request: Request, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(code=code, message=message, trace_id=_trace_id(request)).model_dump(),
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


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


def _parse_run_response(row: dict[str, Any], trace_id: str) -> DocumentParseRunResponse:
    return DocumentParseRunResponse(**row, trace_id=trace_id)


def _chunk_response(row: dict[str, Any], trace_id: str) -> DocumentChunkResponse:
    return DocumentChunkResponse(**row, trace_id=trace_id)


@router.post(
    "/parse",
    response_model=DocumentParseRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Parse a document into traceable chunks",
)
def parse_project_document(
    project_id: str,
    document_id: str,
    payload: DocumentParseRequest,
    request: Request,
) -> DocumentParseRunResponse:
    settings = get_settings()
    repository = AuditRepository(settings)
    document = _load_document(repository, project_id, document_id, request)
    _ensure_parse_tables(settings)
    parse_run = _create_document_parse_run(
        settings=settings,
        project_id=project_id,
        document_id=document_id,
        status="RUNNING",
        parser_name="document_parser",
        parser_version="document_parser_v1",
        requires_ocr=False,
        ocr_requested=payload.allow_ocr_fallback,
        ocr_status="REQUESTED" if payload.allow_ocr_fallback else "NOT_REQUESTED",
        failure_reason=None,
        chunks_count=0,
    )
    result = parse_document(
        Path(str(document["storage_path"])),
        str(document["original_filename"]),
    )
    ocr_status = _ocr_status(result.requires_ocr, payload.allow_ocr_fallback)
    completed_run = _complete_document_parse_run(
        settings=settings,
        project_id=project_id,
        document_id=document_id,
        parse_run_id=str(parse_run["parse_run_id"]),
        status=result.status,
        parser_name=result.parser_name,
        parser_version=result.parser_version,
        requires_ocr=result.requires_ocr,
        ocr_requested=payload.allow_ocr_fallback,
        ocr_status=ocr_status,
        failure_reason=result.failure_reason,
        chunks=result.chunks,
    )
    if completed_run is None:
        raise _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            request,
            "parse_run_not_updated",
            "Document parse run could not be completed.",
        )
    return _parse_run_response(completed_run, _trace_id(request))


@router.get(
    "/parse-runs",
    response_model=DocumentParseRunListResponse,
    summary="List document parse runs",
)
def list_document_parse_runs(
    project_id: str,
    document_id: str,
    request: Request,
) -> DocumentParseRunListResponse:
    settings = get_settings()
    repository = AuditRepository(settings)
    _load_document(repository, project_id, document_id, request)
    _ensure_parse_tables(settings)
    trace_id = _trace_id(request)
    items = [
        _parse_run_response(row, trace_id)
        for row in _list_document_parse_runs(settings, project_id, document_id)
    ]
    return DocumentParseRunListResponse(items=items, total=len(items))


@router.get(
    "/chunks",
    response_model=DocumentChunkListResponse,
    summary="List traceable parsed document chunks",
)
def list_document_chunks(
    project_id: str,
    document_id: str,
    request: Request,
) -> DocumentChunkListResponse:
    settings = get_settings()
    repository = AuditRepository(settings)
    _load_document(repository, project_id, document_id, request)
    _ensure_parse_tables(settings)
    trace_id = _trace_id(request)
    items = [
        _chunk_response(row, trace_id)
        for row in _list_document_chunks(settings, project_id, document_id)
    ]
    return DocumentChunkListResponse(items=items, total=len(items))


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


def _ocr_status(requires_ocr: bool, ocr_requested: bool) -> str:
    if not requires_ocr:
        return "NOT_REQUESTED"
    if ocr_requested:
        return "NOT_AVAILABLE"
    return "NOT_REQUESTED"


def _ensure_parse_tables(settings: Any) -> None:
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
            """
        )


def _create_document_parse_run(
    *,
    settings: Any,
    project_id: str,
    document_id: str,
    status: str,
    parser_name: str,
    parser_version: str,
    requires_ocr: bool,
    ocr_requested: bool,
    ocr_status: str,
    failure_reason: str | None,
    chunks_count: int,
) -> dict[str, Any]:
    parse_run_id = str(uuid4())
    timestamp = utc_now()
    with get_connection(settings) as connection:
        connection.execute(
            """
            INSERT INTO document_parse_runs (
                parse_run_id, project_id, document_id, status, parser_name,
                parser_version, requires_ocr, ocr_requested, ocr_status,
                failure_reason, chunks_count, started_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parse_run_id,
                project_id,
                document_id,
                status,
                parser_name,
                parser_version,
                int(requires_ocr),
                int(ocr_requested),
                ocr_status,
                failure_reason,
                chunks_count,
                timestamp,
                None,
            ),
        )
        row = connection.execute(
            """
            SELECT * FROM document_parse_runs
            WHERE project_id = ? AND document_id = ? AND parse_run_id = ?
            """,
            (project_id, document_id, parse_run_id),
        ).fetchone()
    item = _parse_run_row_to_dict(row)
    if item is None:
        raise RuntimeError("Created document parse run could not be loaded")
    return item


def _complete_document_parse_run(
    *,
    settings: Any,
    project_id: str,
    document_id: str,
    parse_run_id: str,
    status: str,
    parser_name: str,
    parser_version: str,
    requires_ocr: bool,
    ocr_requested: bool,
    ocr_status: str,
    failure_reason: str | None,
    chunks: list[ParsedChunk],
) -> dict[str, Any] | None:
    completed_at = utc_now()
    with get_connection(settings) as connection:
        connection.execute(
            """
            DELETE FROM document_chunks
            WHERE project_id = ? AND document_id = ? AND parse_run_id = ?
            """,
            (project_id, document_id, parse_run_id),
        )
        connection.executemany(
            """
            INSERT INTO document_chunks (
                chunk_id, parse_run_id, project_id, document_id, chunk_type,
                sequence_number, text, content_json, page_number, sheet_name,
                row_number, paragraph_number, table_index, source_locator,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(uuid4()),
                    parse_run_id,
                    project_id,
                    document_id,
                    chunk.chunk_type,
                    chunk.sequence_number,
                    chunk.text,
                    _json_dumps(chunk.content),
                    chunk.page_number,
                    chunk.sheet_name,
                    chunk.row_number,
                    chunk.paragraph_number,
                    chunk.table_index,
                    chunk.source_locator,
                    completed_at,
                )
                for chunk in chunks
            ],
        )
        connection.execute(
            """
            UPDATE document_parse_runs
            SET status = ?, parser_name = ?, parser_version = ?, requires_ocr = ?,
                ocr_requested = ?, ocr_status = ?, failure_reason = ?,
                chunks_count = ?, completed_at = ?
            WHERE project_id = ? AND document_id = ? AND parse_run_id = ?
            """,
            (
                status,
                parser_name,
                parser_version,
                int(requires_ocr),
                int(ocr_requested),
                ocr_status,
                failure_reason,
                len(chunks),
                completed_at,
                project_id,
                document_id,
                parse_run_id,
            ),
        )
        row = connection.execute(
            """
            SELECT * FROM document_parse_runs
            WHERE project_id = ? AND document_id = ? AND parse_run_id = ?
            """,
            (project_id, document_id, parse_run_id),
        ).fetchone()
    return _parse_run_row_to_dict(row)


def _list_document_parse_runs(
    settings: Any,
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
    settings: Any,
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
