from __future__ import annotations

from app.orchestrator.procedure_registry import evaluate_readiness
from app.schemas.procedure_registry import ProcedureDefinition
from app.schemas.procedure_state import ProcedureExecutionStatus, ProcedureStateSource


class ProcedureStateMachineError(ValueError):
    """Raised when a procedure state transition is not allowed."""


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "NOT_STARTED": {
        "READY",
        "PARTIAL",
        "BLOCKED",
        "NOT_APPLICABLE",
        "NOT_PERFORMED",
    },
    "READY": {
        "RUNNING",
        "PARTIAL",
        "BLOCKED",
        "NOT_APPLICABLE",
        "NOT_PERFORMED",
    },
    "RUNNING": {"COMPLETED", "PARTIAL", "BLOCKED", "ABSTAINED"},
    "COMPLETED": set(),
    "PARTIAL": {
        "READY",
        "RUNNING",
        "COMPLETED",
        "BLOCKED",
        "ABSTAINED",
        "NOT_APPLICABLE",
        "NOT_PERFORMED",
    },
    "NOT_APPLICABLE": {"READY", "NOT_STARTED"},
    "NOT_PERFORMED": {"READY", "NOT_STARTED"},
    "BLOCKED": {
        "READY",
        "PARTIAL",
        "ABSTAINED",
        "NOT_APPLICABLE",
        "NOT_PERFORMED",
    },
    "ABSTAINED": {"READY", "PARTIAL", "NOT_APPLICABLE", "NOT_PERFORMED"},
}


def validate_transition(
    *,
    from_status: ProcedureExecutionStatus | None,
    to_status: ProcedureExecutionStatus,
    source_type: ProcedureStateSource,
    reason: str,
    abstention_level: str | None,
    related_evidence_ids: list[str],
) -> None:
    if not reason.strip():
        raise ProcedureStateMachineError("status transition reason is required")
    if to_status == "NOT_PERFORMED" and source_type not in {"auditor", "project_config"}:
        raise ProcedureStateMachineError(
            "AI or system cannot mark a procedure as NOT_PERFORMED"
        )
    if to_status == "NOT_APPLICABLE" and source_type not in {
        "auditor",
        "project_config",
    }:
        raise ProcedureStateMachineError(
            "NOT_APPLICABLE must be set by auditor or project_config"
        )
    if to_status == "ABSTAINED" and abstention_level is None:
        raise ProcedureStateMachineError(
            "abstention_level is required when status is ABSTAINED"
        )
    if to_status == "COMPLETED" and not related_evidence_ids:
        raise ProcedureStateMachineError(
            "COMPLETED requires at least one related Evidence Object"
        )
    if from_status is None or from_status == to_status:
        return
    if to_status not in ALLOWED_TRANSITIONS[from_status]:
        raise ProcedureStateMachineError(
            f"transition from {from_status} to {to_status} is not allowed"
        )


def status_from_registry_readiness(
    *,
    procedure: ProcedureDefinition,
    available_inputs: dict[str, bool],
    completed_procedures: list[str],
) -> tuple[ProcedureExecutionStatus, str, list[str]]:
    readiness = evaluate_readiness(
        procedure=procedure,
        available_inputs=available_inputs,
        completed_procedures=completed_procedures,
    )
    blocked_by = [
        *readiness.missing_required_inputs,
        *readiness.missing_upstream_dependencies,
    ]
    if readiness.blocked_reason:
        blocked_by.append(readiness.blocked_reason)
    return readiness.readiness_status, readiness.explanation, blocked_by
