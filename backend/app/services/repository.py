import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.core.database import get_connection
from app.services.project_context import CORE_SECTIONS, non_empty_sections


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _date_to_text(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _evidence_row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["extracted_value"] = json.loads(str(item.pop("extracted_value_json")))
    return item


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

    def get_procedure(self, project_id: str, procedure_id: str) -> dict[str, Any] | None:
        with get_connection(self.settings) as connection:
            row = connection.execute(
                "SELECT * FROM procedures WHERE project_id = ? AND procedure_id = ?",
                (project_id, procedure_id),
            ).fetchone()
        return _row_to_dict(row)

    def create_evidence(
        self,
        *,
        project_id: str,
        procedure_id: str | None,
        document_id: str | None,
        source: str,
        extracted_value: Any,
        conclusion: str | None,
        execution_status: str,
        node_status: str,
        judgment_status: str,
        confidence: float | None,
        model_confidence: float | None,
        confidence_level: str | None,
        confidence_basis: str | None,
        reviewer: str | None,
    ) -> dict[str, Any]:
        evidence_id = str(uuid4())
        timestamp = utc_now()
        with get_connection(self.settings) as connection:
            connection.execute(
                """
                INSERT INTO evidence (
                    evidence_id, project_id, procedure_id, document_id, source,
                    extracted_value_json, conclusion, execution_status, node_status,
                    judgment_status, confidence, model_confidence, confidence_level,
                    confidence_basis, reviewer, schema_version, object_version,
                    timestamp, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    project_id,
                    procedure_id,
                    document_id,
                    source,
                    _json_dumps(extracted_value),
                    conclusion,
                    execution_status,
                    node_status,
                    judgment_status,
                    confidence,
                    model_confidence,
                    confidence_level,
                    confidence_basis,
                    reviewer,
                    1,
                    1,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            evidence = self._get_evidence_with_connection(connection, project_id, evidence_id)
            if evidence is None:
                raise RuntimeError("Created evidence could not be loaded")
            self._create_evidence_version(connection, evidence)
        return evidence

    def get_evidence(self, project_id: str, evidence_id: str) -> dict[str, Any] | None:
        with get_connection(self.settings) as connection:
            return self._get_evidence_with_connection(connection, project_id, evidence_id)

    def list_evidence(self, project_id: str) -> list[dict[str, Any]]:
        with get_connection(self.settings) as connection:
            rows = connection.execute(
                "SELECT * FROM evidence WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
        return [item for row in rows if (item := _evidence_row_to_dict(row)) is not None]

    def update_evidence(
        self,
        *,
        project_id: str,
        evidence_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        allowed_columns = {
            "execution_status",
            "node_status",
            "judgment_status",
            "conclusion",
            "confidence",
            "model_confidence",
            "confidence_level",
            "confidence_basis",
            "reviewer",
        }
        update_columns = [column for column in updates if column in allowed_columns]
        if not update_columns:
            return self.get_evidence(project_id, evidence_id)

        timestamp = utc_now()
        with get_connection(self.settings) as connection:
            current = self._get_evidence_with_connection(connection, project_id, evidence_id)
            if current is None:
                return None

            assignments = [f"{column} = ?" for column in update_columns]
            assignments.extend(["object_version = ?", "timestamp = ?", "updated_at = ?"])
            parameters = [updates[column] for column in update_columns]
            parameters.extend([int(current["object_version"]) + 1, timestamp, timestamp])
            parameters.extend([project_id, evidence_id])
            connection.execute(
                f"""
                UPDATE evidence
                SET {", ".join(assignments)}
                WHERE project_id = ? AND evidence_id = ?
                """,
                tuple(parameters),
            )
            evidence = self._get_evidence_with_connection(connection, project_id, evidence_id)
            if evidence is None:
                raise RuntimeError("Updated evidence could not be loaded")
            self._create_evidence_version(connection, evidence)
        return evidence

    def get_evidence_version(
        self,
        *,
        project_id: str,
        evidence_id: str,
        object_version: int,
    ) -> dict[str, Any] | None:
        with get_connection(self.settings) as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM evidence_versions
                WHERE project_id = ? AND evidence_id = ? AND object_version = ?
                """,
                (project_id, evidence_id, object_version),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["payload_json"]))

    def _get_evidence_with_connection(
        self,
        connection: Any,
        project_id: str,
        evidence_id: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT * FROM evidence WHERE project_id = ? AND evidence_id = ?",
            (project_id, evidence_id),
        ).fetchone()
        return _evidence_row_to_dict(row)

    def _create_evidence_version(self, connection: Any, evidence: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO evidence_versions (
                version_id, evidence_id, project_id, object_version, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                evidence["evidence_id"],
                evidence["project_id"],
                evidence["object_version"],
                _json_dumps(evidence),
                utc_now(),
            ),
        )


    def create_project_context_version(
        self,
        *,
        project_id: str,
        payload: dict[str, Any],
        changed_by: str | None,
        change_reason: str | None,
    ) -> dict[str, Any]:
        """Append a new immutable Project Context snapshot version.

        Version 1 is created when no context exists yet; every later write
        increments the version, keeps all history, and marks the new row as
        the current one.  ``changed_sections`` records which of the five MVP
        core sections differ from the previous version.
        """
        timestamp = utc_now()
        with get_connection(self.settings) as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """
                SELECT version, payload_json
                FROM project_context_versions
                WHERE project_id = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()

            if previous is None:
                version = 1
                changed_sections = non_empty_sections(payload)
            else:
                version = int(previous["version"]) + 1
                old_payload = json.loads(previous["payload_json"])
                changed_sections = [
                    section
                    for section, _ in CORE_SECTIONS
                    if old_payload.get(section) != payload.get(section)
                ]

            connection.execute(
                "UPDATE project_context_versions SET is_current = 0 WHERE project_id = ?",
                (project_id,),
            )
            connection.execute(
                """
                INSERT INTO project_context_versions (
                    version_id, project_id, version, payload_json,
                    changed_by, change_reason, changed_sections,
                    is_current, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    project_id,
                    version,
                    json.dumps(payload, ensure_ascii=False),
                    changed_by,
                    change_reason,
                    json.dumps(changed_sections, ensure_ascii=False),
                    1,
                    timestamp,
                ),
            )

        current = self.get_project_context(project_id)
        if current is None:
            raise RuntimeError("Created project context version could not be loaded")
        return current

    def get_project_context(self, project_id: str) -> dict[str, Any] | None:
        with get_connection(self.settings) as connection:
            row = connection.execute(
                """
                SELECT * FROM project_context_versions
                WHERE project_id = ? AND is_current = 1
                """,
                (project_id,),
            ).fetchone()
        return _row_to_dict(row)

    def list_project_context_versions(self, project_id: str) -> list[dict[str, Any]]:
        with get_connection(self.settings) as connection:
            rows = connection.execute(
                """
                SELECT * FROM project_context_versions
                WHERE project_id = ?
                ORDER BY version DESC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_project_context_version(
        self, project_id: str, version: int
    ) -> dict[str, Any] | None:
        with get_connection(self.settings) as connection:
            row = connection.execute(
                """
                SELECT * FROM project_context_versions
                WHERE project_id = ? AND version = ?
                """,
                (project_id, version),
            ).fetchone()
        return _row_to_dict(row)


def new_document_id() -> str:
    return str(uuid4())
