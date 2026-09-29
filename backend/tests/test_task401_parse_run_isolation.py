from pathlib import Path

from app.api.routes.contract_extraction import (
    _create_contract_extraction_run,
    _ensure_contract_extraction_tables,
    _list_document_chunks,
)
from app.core.config import Settings
from app.core.database import get_connection, initialize_database


def test_contract_extraction_chunk_lookup_is_scoped_to_parse_run(tmp_path: Path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "audit.sqlite3"),
        upload_dir=str(tmp_path / "uploads"),
    )
    initialize_database(settings)
    _ensure_contract_extraction_tables(settings)
    _seed_document_with_three_parse_runs(settings)

    chunks = _list_document_chunks(settings, "project-1", "document-1", "parse-run-2")

    assert [chunk["chunk_id"] for chunk in chunks] == ["chunk-2"]
    assert [chunk["text"] for chunk in chunks] == ["履约义务：第2次解析"]


def test_contract_extraction_run_persists_parse_run_id(tmp_path: Path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "audit.sqlite3"),
        upload_dir=str(tmp_path / "uploads"),
    )
    initialize_database(settings)
    _ensure_contract_extraction_tables(settings)
    _seed_document_with_three_parse_runs(settings)

    run = _create_contract_extraction_run(
        settings=settings,
        project_id="project-1",
        document_id="document-1",
        parse_run_id="parse-run-2",
        evidence_id=None,
        status="COMPLETED",
        extractor_type="rule_based",
        extractor_version="contract_extraction_rule_v1",
        fields=[],
        failure_reason=None,
    )

    assert run["parse_run_id"] == "parse-run-2"


def _seed_document_with_three_parse_runs(settings: Settings) -> None:
    with get_connection(settings) as connection:
        connection.execute(
            """
            INSERT INTO projects (
                project_id, name, client_name, audit_period_start, audit_period_end,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "project-1",
                "TASK-401",
                None,
                None,
                None,
                "active",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO documents (
                document_id, project_id, original_filename, stored_filename, content_type,
                size_bytes, checksum_sha256, storage_path, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "document-1",
                "project-1",
                "contract.txt",
                "stored-contract.txt",
                "text/plain",
                1,
                "sha256",
                "/tmp/contract.txt",
                "uploaded",
                "2026-01-01T00:00:00Z",
            ),
        )
        for index in range(1, 4):
            parse_run_id = f"parse-run-{index}"
            timestamp = f"2026-01-01T00:00:0{index}Z"
            connection.execute(
                """
                INSERT INTO document_parse_runs (
                    parse_run_id, project_id, document_id, status, parser_name,
                    parser_version, requires_ocr, ocr_requested, ocr_status,
                    failure_reason, chunks_count, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    parse_run_id,
                    "project-1",
                    "document-1",
                    "COMPLETED",
                    "document_parser",
                    "document_parser_v1",
                    0,
                    0,
                    "NOT_REQUESTED",
                    None,
                    1,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO document_chunks (
                    chunk_id, parse_run_id, project_id, document_id, chunk_type,
                    sequence_number, text, content_json, source_locator, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"chunk-{index}",
                    parse_run_id,
                    "project-1",
                    "document-1",
                    "line",
                    1,
                    f"履约义务：第{index}次解析",
                    "{}",
                    "line=1",
                    timestamp,
                ),
            )
