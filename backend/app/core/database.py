import sqlite3
from pathlib import Path

from app.core.config import Settings


def resolve_database_path(settings: Settings) -> Path:
    path = Path(settings.database_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    return path.resolve()


def get_connection(settings: Settings) -> sqlite3.Connection:
    database_path = resolve_database_path(settings)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _add_missing_columns(
    connection: sqlite3.Connection,
    table_name: str,
    column_definitions: dict[str, str],
) -> None:
    existing_columns = _table_columns(connection, table_name)
    for column_name, column_definition in column_definitions.items():
        if column_name not in existing_columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}")


def initialize_database(settings: Settings) -> None:
    with get_connection(settings) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                client_name TEXT,
                audit_period_start TEXT,
                audit_period_end TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                content_type TEXT,
                size_bytes INTEGER NOT NULL,
                checksum_sha256 TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS procedures (
                procedure_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                procedure_id TEXT,
                document_id TEXT,
                source TEXT NOT NULL,
                extracted_value_json TEXT NOT NULL,
                conclusion TEXT,
                execution_status TEXT NOT NULL,
                node_status TEXT NOT NULL,
                judgment_status TEXT NOT NULL,
                confidence REAL,
                model_confidence REAL,
                confidence_level TEXT,
                confidence_basis TEXT,
                reviewer TEXT,
                schema_version INTEGER NOT NULL,
                object_version INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(project_id),
                FOREIGN KEY (procedure_id) REFERENCES procedures(procedure_id),
                FOREIGN KEY (document_id) REFERENCES documents(document_id)
            );

            CREATE TABLE IF NOT EXISTS evidence_versions (
                version_id TEXT PRIMARY KEY,
                evidence_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                object_version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id),
                FOREIGN KEY (project_id) REFERENCES projects(project_id),
                UNIQUE (evidence_id, object_version)
            );

            CREATE TABLE IF NOT EXISTS reviews (
                review_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                evidence_id TEXT,
                reviewer TEXT,
                decision TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(project_id),
                FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
            );

            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                error_type TEXT,
                error_message TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS normalized_values (
                normalized_value_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                evidence_id TEXT,
                document_id TEXT,
                procedure_id TEXT,
                field_name TEXT NOT NULL,
                value_type TEXT NOT NULL,
                raw_value_json TEXT NOT NULL,
                standard_value_json TEXT NOT NULL,
                normalization_rule TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                quality_score INTEGER NOT NULL,
                issues_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(project_id),
                FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id),
                FOREIGN KEY (document_id) REFERENCES documents(document_id),
                FOREIGN KEY (procedure_id) REFERENCES procedures(procedure_id)
            );

            CREATE TABLE IF NOT EXISTS dataset_quality_snapshots (
                dataset_quality_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                dataset_name TEXT NOT NULL,
                total_records INTEGER NOT NULL,
                usable_records INTEGER NOT NULL,
                partial_records INTEGER NOT NULL,
                rejected_records INTEGER NOT NULL,
                quality_score INTEGER NOT NULL,
                quality_status TEXT NOT NULL,
                procedure_readiness TEXT NOT NULL,
                issues_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS project_context_versions (
                version_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                changed_by TEXT,
                change_reason TEXT,
                changed_sections TEXT NOT NULL,
                is_current INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(project_id),
                UNIQUE (project_id, version)
            );
            """
        )
        _add_missing_columns(
            connection,
            "evidence",
            {
                "source": "source TEXT NOT NULL DEFAULT 'unknown'",
                "extracted_value_json": "extracted_value_json TEXT NOT NULL DEFAULT 'null'",
                "conclusion": "conclusion TEXT",
                "execution_status": "execution_status TEXT NOT NULL DEFAULT 'not_started'",
                "node_status": "node_status TEXT NOT NULL DEFAULT 'draft'",
                "judgment_status": "judgment_status TEXT NOT NULL DEFAULT 'PENDING_REVIEW'",
                "confidence": "confidence REAL",
                "model_confidence": "model_confidence REAL",
                "confidence_level": "confidence_level TEXT",
                "confidence_basis": "confidence_basis TEXT",
                "reviewer": "reviewer TEXT",
                "schema_version": "schema_version INTEGER NOT NULL DEFAULT 1",
                "object_version": "object_version INTEGER NOT NULL DEFAULT 1",
                "timestamp": "timestamp TEXT NOT NULL DEFAULT ''",
                "created_at": "created_at TEXT NOT NULL DEFAULT ''",
                "updated_at": "updated_at TEXT NOT NULL DEFAULT ''",
            },
        )
