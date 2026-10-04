import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.core.database import get_connection


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _procedure_state_row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["related_evidence_ids"] = json.loads(str(item.pop("related_evidence_ids_json")))
    item["blocked_by"] = json.loads(str(item.pop("blocked_by_json")))
    return item


def _procedure_state_transition_row_to_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


class ProcedureStateRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_procedure_state(
        self,
        *,
        project_id: str,
        procedure_id: str,
        procedure_name: str,
        status: str,
        status_reason: str,
        source_type: str,
        abstention_level: str | None,
        related_evidence_ids: list[str],
        blocked_by: list[str],
        actor: str | None = None,
        trace_id: str = "",
    ) -> dict[str, Any]:
        state_id = str(uuid4())
        timestamp = _utc_now()
        with get_connection(self.settings) as connection:
            connection.execute(
                """
                INSERT INTO procedure_execution_states (
                    state_id, project_id, procedure_id, procedure_name, status,
                    status_reason, source_type, abstention_level,
                    related_evidence_ids_json, blocked_by_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state_id,
                    project_id,
                    procedure_id,
                    procedure_name,
                    status,
                    status_reason,
                    source_type,
                    abstention_level,
                    _json_dumps(related_evidence_ids),
                    _json_dumps(blocked_by),
                    timestamp,
                    timestamp,
                ),
            )
            self._create_procedure_state_transition(
                connection=connection,
                state_id=state_id,
                project_id=project_id,
                procedure_id=procedure_id,
                from_status=None,
                to_status=status,
                reason=status_reason,
                triggered_by=source_type,
                actor=actor,
                trace_id=trace_id,
                created_at=timestamp,
            )
            row = connection.execute(
                """
                SELECT * FROM procedure_execution_states
                WHERE project_id = ? AND state_id = ?
                """,
                (project_id, state_id),
            ).fetchone()
        item = _procedure_state_row_to_dict(row)
        if item is None:
            raise RuntimeError("Created procedure state could not be loaded")
        return item

    def upsert_procedure_state(
        self,
        *,
        project_id: str,
        procedure_id: str,
        procedure_name: str,
        status: str,
        status_reason: str,
        source_type: str,
        abstention_level: str | None,
        related_evidence_ids: list[str],
        blocked_by: list[str],
        actor: str | None = None,
        trace_id: str = "",
    ) -> dict[str, Any]:
        current = self.get_procedure_state_by_procedure(project_id, procedure_id)
        if current is None:
            return self.create_procedure_state(
                project_id=project_id,
                procedure_id=procedure_id,
                procedure_name=procedure_name,
                status=status,
                status_reason=status_reason,
                source_type=source_type,
                abstention_level=abstention_level,
                related_evidence_ids=related_evidence_ids,
                blocked_by=blocked_by,
                actor=actor,
                trace_id=trace_id,
            )
        return self.update_procedure_state(
            project_id=project_id,
            state_id=str(current["state_id"]),
            status=status,
            status_reason=status_reason,
            source_type=source_type,
            abstention_level=abstention_level,
            related_evidence_ids=related_evidence_ids,
            blocked_by=blocked_by,
            actor=actor,
            trace_id=trace_id,
        )

    def get_procedure_state(self, project_id: str, state_id: str) -> dict[str, Any] | None:
        with get_connection(self.settings) as connection:
            row = connection.execute(
                """
                SELECT * FROM procedure_execution_states
                WHERE project_id = ? AND state_id = ?
                """,
                (project_id, state_id),
            ).fetchone()
        return _procedure_state_row_to_dict(row)

    def get_procedure_state_by_procedure(
        self,
        project_id: str,
        procedure_id: str,
    ) -> dict[str, Any] | None:
        with get_connection(self.settings) as connection:
            row = connection.execute(
                """
                SELECT * FROM procedure_execution_states
                WHERE project_id = ? AND procedure_id = ?
                """,
                (project_id, procedure_id),
            ).fetchone()
        return _procedure_state_row_to_dict(row)

    def list_procedure_states(self, project_id: str) -> list[dict[str, Any]]:
        with get_connection(self.settings) as connection:
            rows = connection.execute(
                """
                SELECT * FROM procedure_execution_states
                WHERE project_id = ?
                ORDER BY procedure_id ASC
                """,
                (project_id,),
            ).fetchall()
        return [
            item
            for row in rows
            if (item := _procedure_state_row_to_dict(row)) is not None
        ]

    def update_procedure_state(
        self,
        *,
        project_id: str,
        state_id: str,
        status: str,
        status_reason: str,
        source_type: str,
        abstention_level: str | None,
        related_evidence_ids: list[str],
        blocked_by: list[str],
        actor: str | None = None,
        trace_id: str = "",
    ) -> dict[str, Any] | None:
        timestamp = _utc_now()
        with get_connection(self.settings) as connection:
            current = connection.execute(
                """
                SELECT * FROM procedure_execution_states
                WHERE project_id = ? AND state_id = ?
                """,
                (project_id, state_id),
            ).fetchone()
            if current is None:
                return None
            current_item = dict(current)
            connection.execute(
                """
                UPDATE procedure_execution_states
                SET status = ?, status_reason = ?, source_type = ?,
                    abstention_level = ?, related_evidence_ids_json = ?,
                    blocked_by_json = ?, updated_at = ?
                WHERE project_id = ? AND state_id = ?
                """,
                (
                    status,
                    status_reason,
                    source_type,
                    abstention_level,
                    _json_dumps(related_evidence_ids),
                    _json_dumps(blocked_by),
                    timestamp,
                    project_id,
                    state_id,
                ),
            )
            self._create_procedure_state_transition(
                connection=connection,
                state_id=state_id,
                project_id=project_id,
                procedure_id=str(current_item["procedure_id"]),
                from_status=str(current_item["status"]),
                to_status=status,
                reason=status_reason,
                triggered_by=source_type,
                actor=actor,
                trace_id=trace_id,
                created_at=timestamp,
            )
            row = connection.execute(
                """
                SELECT * FROM procedure_execution_states
                WHERE project_id = ? AND state_id = ?
                """,
                (project_id, state_id),
            ).fetchone()
        return _procedure_state_row_to_dict(row)

    def list_procedure_state_transitions(
        self,
        project_id: str,
        state_id: str,
    ) -> list[dict[str, Any]]:
        with get_connection(self.settings) as connection:
            rows = connection.execute(
                """
                SELECT * FROM procedure_state_transitions
                WHERE project_id = ? AND state_id = ?
                ORDER BY created_at ASC
                """,
                (project_id, state_id),
            ).fetchall()
        return [
            item
            for row in rows
            if (item := _procedure_state_transition_row_to_dict(row)) is not None
        ]

    def _create_procedure_state_transition(
        self,
        *,
        connection: Any,
        state_id: str,
        project_id: str,
        procedure_id: str,
        from_status: str | None,
        to_status: str,
        reason: str,
        triggered_by: str,
        actor: str | None,
        trace_id: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO procedure_state_transitions (
                transition_id, state_id, project_id, procedure_id, from_status,
                to_status, reason, triggered_by, actor, trace_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                state_id,
                project_id,
                procedure_id,
                from_status,
                to_status,
                reason,
                triggered_by,
                actor,
                trace_id,
                created_at,
            ),
        )
