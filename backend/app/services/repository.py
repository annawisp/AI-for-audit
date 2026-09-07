from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.core.database import get_connection


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _date_to_text(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


class AuditRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_project(
        self,
        *,
        name: str,
        client_name: str | None,
        audit_period_start: date | None,
        audit_period_end: date | None,
    ) -> dict[str, Any]:
        project_id = str(uuid4())
        timestamp = utc_now()
        with get_connection(self.settings) as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    project_id, name, client_name, audit_period_start,
                    audit_period_end, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    name,
                    client_name,
                    _date_to_text(audit_period_start),
                    _date_to_text(audit_period_end),
                    "active",
                    timestamp,
                    timestamp,
                ),
            )
        project = self.get_project(project_id)
        if project is None:
            raise RuntimeError("Created project could not be loaded")
        return project

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with get_connection(self.settings) as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return _row_to_dict(row)

    def list_projects(self) -> list[dict[str, Any]]:
        with get_connection(self.settings) as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY created_at DESC",
            ).fetchall()
        return [dict(row) for row in rows]

    def create_document(
        self,
        *,
        document_id: str,
        project_id: str,
        original_filename: str,
        stored_filename: str,
        content_type: str | None,
        size_bytes: int,
        checksum_sha256: str,
        storage_path: str,
    ) -> dict[str, Any]:
        timestamp = utc_now()
        with get_connection(self.settings) as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    document_id, project_id, original_filename, stored_filename,
                    content_type, size_bytes, checksum_sha256, storage_path,
                    status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    project_id,
                    original_filename,
                    stored_filename,
                    content_type,
                    size_bytes,
                    checksum_sha256,
                    storage_path,
                    "uploaded",
                    timestamp,
                ),
            )
        document = self.get_document(project_id, document_id)
        if document is None:
            raise RuntimeError("Created document could not be loaded")
        return document

    def get_document(self, project_id: str, document_id: str) -> dict[str, Any] | None:
        with get_connection(self.settings) as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE project_id = ? AND document_id = ?",
                (project_id, document_id),
            ).fetchone()
        return _row_to_dict(row)

    def list_documents(self, project_id: str) -> list[dict[str, Any]]:
        with get_connection(self.settings) as connection:
            rows = connection.execute(
                "SELECT * FROM documents WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def new_document_id() -> str:
    return str(uuid4())
