from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas.procedure_registry import (
    ProcedureDefinition,
    ProcedureReadinessResponse,
)

REGISTRY_VERSION = "procedure_registry_v1"
DEFAULT_REGISTRY_PATH = Path(__file__).with_name("procedure_registry.json")

KNOWN_CAPABILITY_IDS = {
    "document_processor",
    "contract_extraction",
    "revenue_recognition_analysis",
    "revenue_risk_identification",
    "data_reconciliation",
}


class ProcedureRegistryConfigError(ValueError):
    """Raised when procedure registry configuration is invalid."""


def list_procedures(
    registry_path: Path | str | None = None,
) -> list[ProcedureDefinition]:
    return list(load_procedure_registry(registry_path))


def get_procedure(
    procedure_id: str,
    registry_path: Path | str | None = None,
) -> ProcedureDefinition | None:
    return {
        procedure.procedure_id: procedure
        for procedure in load_procedure_registry(registry_path)
    }.get(procedure_id)


def load_procedure_registry(
    registry_path: Path | str | None = None,
) -> tuple[ProcedureDefinition, ...]:
    if registry_path is None:
        return _load_default_procedure_registry()
    return _load_registry_from_path(Path(registry_path))


@lru_cache(maxsize=1)
def _load_default_procedure_registry() -> tuple[ProcedureDefinition, ...]:
    return _load_registry_from_path(DEFAULT_REGISTRY_PATH)


def _load_registry_from_path(
    registry_path: Path,
) -> tuple[ProcedureDefinition, ...]:
    try:
        raw_config = json.loads(registry_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ProcedureRegistryConfigError(
            f"procedure registry config cannot be read: {registry_path}"
        ) from error
    except json.JSONDecodeError as error:
        raise ProcedureRegistryConfigError(
            f"procedure registry config is not valid JSON: {error.msg}"
        ) from error

    procedures_data = _extract_procedures_data(raw_config)
    procedures = _parse_procedure_definitions(procedures_data)
    _validate_procedure_registry(procedures)
    return tuple(procedures)


def _extract_procedures_data(raw_config: Any) -> list[Any]:
    if isinstance(raw_config, dict) and isinstance(raw_config.get("procedures"), list):
        return raw_config["procedures"]
    if isinstance(raw_config, list):
        return raw_config
    raise ProcedureRegistryConfigError(
        "procedure registry config must contain a procedures list"
    )


def _parse_procedure_definitions(
    procedures_data: list[Any],
) -> list[ProcedureDefinition]:
    procedures: list[ProcedureDefinition] = []
    for index, procedure_data in enumerate(procedures_data, start=1):
        try:
            procedures.append(ProcedureDefinition.model_validate(procedure_data))
        except ValidationError as error:
            raise ProcedureRegistryConfigError(
                f"procedure registry item #{index} failed schema validation"
            ) from error
    return procedures


def _validate_procedure_registry(
    procedures: list[ProcedureDefinition],
) -> None:
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    procedure_ids = {procedure.procedure_id for procedure in procedures}

    for procedure in procedures:
        if procedure.procedure_id in seen_ids:
            duplicate_ids.add(procedure.procedure_id)
        seen_ids.add(procedure.procedure_id)

    if duplicate_ids:
        raise ProcedureRegistryConfigError(
            "duplicate procedure_id: " + ", ".join(sorted(duplicate_ids))
        )

    for procedure in procedures:
        _validate_capability_references(procedure)
        _validate_upstream_dependencies(procedure, procedure_ids)
        _validate_minimum_input_groups(procedure)


def _validate_capability_references(procedure: ProcedureDefinition) -> None:
    unknown_capabilities = [
        capability.capability_id
        for capability in procedure.capabilities
        if capability.capability_id not in KNOWN_CAPABILITY_IDS
    ]
    if unknown_capabilities:
        raise ProcedureRegistryConfigError(
            f"{procedure.procedure_id} references unknown capability: "
            + ", ".join(sorted(unknown_capabilities))
        )


def _validate_upstream_dependencies(
    procedure: ProcedureDefinition,
    procedure_ids: set[str],
) -> None:
    missing_dependencies = [
        dependency
        for dependency in procedure.upstream_dependencies
        if dependency not in procedure_ids
    ]
    if missing_dependencies:
        raise ProcedureRegistryConfigError(
            f"{procedure.procedure_id} references unknown upstream procedure: "
            + ", ".join(sorted(missing_dependencies))
        )


def _validate_minimum_input_groups(procedure: ProcedureDefinition) -> None:
    known_input_ids = {
        input_item.input_id
        for input_item in (
            procedure.required_inputs
            + procedure.optional_inputs
            + procedure.dependent_inputs
        )
    }
    unknown_inputs = sorted(
        {
            input_id
            for group in procedure.execution_policy.minimum_required_input_groups
            for input_id in group
            if input_id not in known_input_ids
        }
    )
    if unknown_inputs:
        raise ProcedureRegistryConfigError(
            f"{procedure.procedure_id} minimum input group references unknown input: "
            + ", ".join(unknown_inputs)
        )


def evaluate_readiness(
    *,
    procedure: ProcedureDefinition,
    available_inputs: dict[str, bool],
    completed_procedures: list[str],
    mark_not_applicable: bool = False,
    not_applicable_reason: str | None = None,
) -> ProcedureReadinessResponse:
    available = {
        input_id
        for input_id, is_available in available_inputs.items()
        if is_available
    }
    completed = set(completed_procedures)
    required_ids = [item.input_id for item in procedure.required_inputs]
    optional_ids = [item.input_id for item in procedure.optional_inputs]
    dependent_ids = [item.input_id for item in procedure.dependent_inputs]
    ready_inputs = sorted(available & set(required_ids + optional_ids + dependent_ids))
    missing_required = [input_id for input_id in required_ids if input_id not in available]
    missing_optional = [input_id for input_id in optional_ids if input_id not in available]
    missing_dependent = [input_id for input_id in dependent_ids if input_id not in available]
    satisfied_upstream = [
        procedure_id
        for procedure_id in procedure.upstream_dependencies
        if procedure_id in completed
    ]
    missing_upstream = [
        procedure_id
        for procedure_id in procedure.upstream_dependencies
        if procedure_id not in completed
    ]

    if mark_not_applicable:
        return _readiness_response(
            procedure=procedure,
            readiness_status="NOT_APPLICABLE",
            ready_inputs=ready_inputs,
            missing_required_inputs=missing_required,
            missing_optional_inputs=missing_optional,
            missing_dependent_inputs=missing_dependent,
            satisfied_upstream_dependencies=satisfied_upstream,
            missing_upstream_dependencies=missing_upstream,
            blocked_reason=None,
            explanation=not_applicable_reason
            or "Procedure is marked not applicable for this scenario.",
        )

    group_blockers = _missing_minimum_groups(
        procedure.execution_policy.minimum_required_input_groups,
        available,
    )
    if missing_required or missing_upstream or group_blockers:
        blocked_reason = _blocked_reason(missing_required, missing_upstream, group_blockers)
        return _readiness_response(
            procedure=procedure,
            readiness_status="BLOCKED",
            ready_inputs=ready_inputs,
            missing_required_inputs=missing_required,
            missing_optional_inputs=missing_optional,
            missing_dependent_inputs=missing_dependent,
            satisfied_upstream_dependencies=satisfied_upstream,
            missing_upstream_dependencies=missing_upstream,
            blocked_reason=blocked_reason,
            explanation=f"{procedure.procedure_name} is blocked: {blocked_reason}",
        )

    if (
        procedure.execution_policy.allow_partial_execution
        and (missing_dependent or _optional_inputs_limit_coverage(procedure, missing_optional))
    ):
        return _readiness_response(
            procedure=procedure,
            readiness_status="PARTIAL",
            ready_inputs=ready_inputs,
            missing_required_inputs=[],
            missing_optional_inputs=missing_optional,
            missing_dependent_inputs=missing_dependent,
            satisfied_upstream_dependencies=satisfied_upstream,
            missing_upstream_dependencies=[],
            blocked_reason=None,
            explanation=(
                f"{procedure.procedure_name} can run partially; missing inputs only "
                "limit dependent or optional analysis."
            ),
        )

    return _readiness_response(
        procedure=procedure,
        readiness_status="READY",
        ready_inputs=ready_inputs,
        missing_required_inputs=[],
        missing_optional_inputs=missing_optional,
        missing_dependent_inputs=missing_dependent,
        satisfied_upstream_dependencies=satisfied_upstream,
        missing_upstream_dependencies=[],
        blocked_reason=None,
        explanation=f"{procedure.procedure_name} is ready to execute.",
    )


def _readiness_response(
    *,
    procedure: ProcedureDefinition,
    readiness_status: str,
    ready_inputs: list[str],
    missing_required_inputs: list[str],
    missing_optional_inputs: list[str],
    missing_dependent_inputs: list[str],
    satisfied_upstream_dependencies: list[str],
    missing_upstream_dependencies: list[str],
    blocked_reason: str | None,
    explanation: str,
) -> ProcedureReadinessResponse:
    return ProcedureReadinessResponse(
        procedure_id=procedure.procedure_id,
        procedure_name=procedure.procedure_name,
        readiness_status=readiness_status,
        ready_inputs=ready_inputs,
        missing_required_inputs=missing_required_inputs,
        missing_optional_inputs=missing_optional_inputs,
        missing_dependent_inputs=missing_dependent_inputs,
        satisfied_upstream_dependencies=satisfied_upstream_dependencies,
        missing_upstream_dependencies=missing_upstream_dependencies,
        blocked_reason=blocked_reason,
        explanation=explanation,
        trace_id="",
    )


def _missing_minimum_groups(
    groups: list[list[str]],
    available_inputs: set[str],
) -> list[list[str]]:
    return [
        group
        for group in groups
        if not any(input_id in available_inputs for input_id in group)
    ]


def _optional_inputs_limit_coverage(
    procedure: ProcedureDefinition,
    missing_optional_inputs: list[str],
) -> bool:
    return (
        procedure.execution_policy.partial_when_optional_missing
        and bool(missing_optional_inputs)
    )


def _blocked_reason(
    missing_required_inputs: list[str],
    missing_upstream_dependencies: list[str],
    missing_minimum_groups: list[list[str]],
) -> str:
    reasons: list[str] = []
    if missing_required_inputs:
        reasons.append("missing required inputs: " + ", ".join(missing_required_inputs))
    if missing_upstream_dependencies:
        reasons.append(
            "missing upstream procedures: " + ", ".join(missing_upstream_dependencies)
        )
    if missing_minimum_groups:
        group_text = [" or ".join(group) for group in missing_minimum_groups]
        reasons.append("missing at least one input from: " + "; ".join(group_text))
    return "; ".join(reasons)
