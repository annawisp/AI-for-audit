from __future__ import annotations

from typing import Any

RULES_VERSION = "task304-rule-based-v2"


def identify_revenue_risks(
    *,
    project: dict[str, Any],
    contract_evidence: dict[str, Any] | None,
    revenue_recognition_evidence: dict[str, Any] | None,
    revenue_records: list[Any] | None,
    enable_semantic_judgment: bool = False,
) -> dict[str, Any]:
    records = revenue_records or []
    contract_fields = _field_map(contract_evidence)
    recognition_value = _extracted_value(revenue_recognition_evidence)

    signals: list[dict[str, Any]] = []
    limitations: list[str] = []

    if contract_evidence is None and revenue_recognition_evidence is None and not records:
        limitations.append("No upstream TASK-302 or TASK-303 evidence was provided.")
        limitations.append("Revenue detail records were not provided.")
        return _abstained_result(
            project=project,
            records=records,
            limitations=limitations,
            source_evidence_ids=[],
            enable_semantic_judgment=enable_semantic_judgment,
        )

    obligations = _field(contract_fields, "performance_obligations")
    obligation_items = _field_values(obligations)
    transaction_price = _field(contract_fields, "transaction_price")
    has_multiple_obligations = len(obligation_items) > 1
    allocation_missing = has_multiple_obligations and not _recognition_has_allocation_basis(
        recognition_value
    )
    if obligations and obligations.get("status") == "CONFLICTING_EVIDENCE":
        signals.append(
            _signal(
                "conflicting_performance_obligations",
                "Conflicting performance obligation evidence",
                None,
                "CONFLICTING",
                "Contract extraction returned conflicting performance obligation evidence.",
                "contract_evidence.performance_obligations",
            )
        )
    elif allocation_missing:
        signals.append(
            _signal(
                "multiple_obligation_allocation",
                "Multiple obligation allocation risk",
                "HIGH",
                "REQUIRES_REVIEW",
                "Structured contract fields show multiple performance obligations "
                "without a documented allocation basis.",
                "contract_evidence.performance_obligations",
            )
        )

    acceptance_terms = _field(contract_fields, "acceptance_terms")
    acceptance_status = _acceptance_status(acceptance_terms)
    if acceptance_status == "CONFLICTING":
        signals.append(
            _signal(
                "conflicting_acceptance_terms",
                "Conflicting acceptance terms",
                None,
                "CONFLICTING",
                "Contract extraction returned both acceptance-required and "
                "acceptance-not-applicable evidence.",
                "contract_evidence.acceptance_terms",
            )
        )
    elif acceptance_status == "REQUIRED":
        signals.append(
            _signal(
                "cutoff_acceptance",
                "Cut-off and acceptance risk",
                "MEDIUM",
                "REQUIRES_REVIEW",
                "Structured contract fields indicate acceptance is required before "
                "or around revenue recognition.",
                "contract_evidence.acceptance_terms",
            )
        )

    if records:
        incomplete = [record for record in records if _is_incomplete_record(record)]
        if incomplete:
            signals.append(
                _signal(
                    "incomplete_revenue_records",
                    "Incomplete revenue record risk",
                    "MEDIUM",
                    "REQUIRES_REVIEW",
                    "One or more revenue records miss recognition date or amount.",
                    "revenue_records",
                )
            )
    else:
        limitations.append(
            "Revenue detail records were not provided; amount-level reconciliation is limited."
        )

    if contract_evidence is None:
        limitations.append("Contract extraction evidence was not provided.")
    elif not contract_fields:
        limitations.append("Contract extraction evidence did not contain structured fields.")
    if transaction_price and transaction_price.get("status") == "MISSING_IN_DOCUMENT":
        limitations.append("Contract transaction price was not found in the document.")

    if not signals:
        signals.append(
            _signal(
                "baseline_low_risk",
                "No elevated rule-based signal",
                "LOW",
                "COMPLETED",
                "No elevated revenue-risk signal was identified from supplied evidence.",
                "rule_engine",
            )
        )

    conflict = any(signal["status"] == "CONFLICTING" for signal in signals)
    high = any(signal["risk_level"] == "HIGH" for signal in signals)
    review = any(signal["status"] == "REQUIRES_REVIEW" for signal in signals)
    evidence_count = (
        int(contract_evidence is not None)
        + int(revenue_recognition_evidence is not None)
        + int(bool(records))
    )
    coverage_ratio = round(evidence_count / 3, 2)
    overall = None if conflict else "HIGH" if high else "MEDIUM" if review else "LOW"
    status = "REQUIRES_REVIEW" if (review or conflict) else "COMPLETED"
    coverage = {
        "contract_evidence": contract_evidence is not None,
        "revenue_recognition_evidence": revenue_recognition_evidence is not None,
        "revenue_record_analysis": bool(records),
        "coverage_ratio": coverage_ratio,
        "rule_coverage_ratio": coverage_ratio,
        "semantic_judgment_coverage": 0.0,
    }
    source_evidence_ids = [
        str(item["evidence_id"])
        for item in [contract_evidence, revenue_recognition_evidence]
        if item
    ]
    project_name = project.get("name", "project")
    conclusion = (
        f"TASK-304 revenue risk identification completed for {project_name}: "
        f"overall risk is {overall or 'not assessed due to conflicting evidence'}."
    )
    return {
        "status": status,
        "overall_risk_level": overall,
        "coverage": coverage,
        "risk_signals": signals,
        "limitations": limitations,
        "source_evidence_ids": source_evidence_ids,
        "rules_version": RULES_VERSION,
        "engine_type": "rule_based",
        "llm_judgment_status": "NOT_REQUESTED"
        if not enable_semantic_judgment
        else "NOT_AVAILABLE",
        "conclusion": conclusion,
        "node_status": "partial" if (review or conflict) else "ready",
        "judgment_status": "PENDING_REVIEW" if (review or conflict) else "AI_GENERATED",
        "confidence_level": "low" if conflict else "medium" if review else "high",
    }


def build_revenue_risk_evidence_value(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "capability": "revenue_risk_identification",
        "rules_version": result["rules_version"],
        "status": result["status"],
        "overall_risk_level": result["overall_risk_level"],
        "coverage": result["coverage"],
        "risk_signals": result["risk_signals"],
        "limitations": result["limitations"],
        "source_evidence_ids": result["source_evidence_ids"],
        "conclusion": result["conclusion"],
    }


def _signal(
    signal_id: str,
    name: str,
    risk_level: str | None,
    status: str,
    rationale: str,
    source: str,
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "name": name,
        "risk_level": risk_level,
        "status": status,
        "rationale": rationale,
        "source": source,
        "is_audit_conclusion": False,
    }


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    return {}


def _is_incomplete_record(record: Any) -> bool:
    value = _model_dump(record)
    return not value.get("recognition_date") or value.get("amount") in (None, "")


def _extracted_value(evidence: dict[str, Any] | None) -> dict[str, Any]:
    value = evidence.get("extracted_value", {}) if evidence else {}
    return value if isinstance(value, dict) else {}


def _field_map(evidence: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    extracted_value = _extracted_value(evidence)
    fields = extracted_value.get("fields", [])
    if not isinstance(fields, list):
        return {}
    return {
        str(field.get("field_name")): field
        for field in fields
        if isinstance(field, dict) and field.get("field_name")
    }


def _field(fields: dict[str, dict[str, Any]], field_name: str) -> dict[str, Any]:
    return fields.get(field_name, {})


def _field_values(field: dict[str, Any]) -> list[Any]:
    if field.get("status") != "EXTRACTED":
        return []
    value = field.get("value")
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _recognition_has_allocation_basis(recognition_value: dict[str, Any]) -> bool:
    assessment = recognition_value.get("performance_obligation_assessment")
    if not isinstance(assessment, dict):
        return False
    allocation_basis = assessment.get("allocation_basis")
    if isinstance(allocation_basis, str):
        return bool(allocation_basis.strip())
    return allocation_basis is not None


def _acceptance_status(field: dict[str, Any]) -> str:
    if not field:
        return "UNKNOWN"
    status = field.get("status")
    if status == "CONFLICTING_EVIDENCE":
        return "CONFLICTING"
    if status == "NOT_APPLICABLE":
        return "NEGATED"
    if status != "EXTRACTED":
        return "UNKNOWN"
    text = " ".join(str(item) for item in _field_values(field))
    if any(marker in text for marker in ("无需验收", "不需要验收", "验收不适用")):
        return "NEGATED"
    return "REQUIRED"


def _abstained_result(
    *,
    project: dict[str, Any],
    records: list[Any],
    limitations: list[str],
    source_evidence_ids: list[str],
    enable_semantic_judgment: bool,
) -> dict[str, Any]:
    coverage = {
        "contract_evidence": False,
        "revenue_recognition_evidence": False,
        "revenue_record_analysis": bool(records),
        "coverage_ratio": 0.0,
        "rule_coverage_ratio": 0.0,
        "semantic_judgment_coverage": 0.0,
    }
    project_name = project.get("name", "project")
    return {
        "status": "ABSTAINED",
        "overall_risk_level": None,
        "coverage": coverage,
        "risk_signals": [
            _signal(
                "insufficient_evidence",
                "Insufficient revenue evidence",
                None,
                "NEED_MORE_EVIDENCE",
                "No upstream evidence or revenue records are available for "
                "revenue-risk identification.",
                "input",
            )
        ],
        "limitations": limitations,
        "source_evidence_ids": source_evidence_ids,
        "rules_version": RULES_VERSION,
        "engine_type": "rule_based",
        "llm_judgment_status": "NOT_REQUESTED"
        if not enable_semantic_judgment
        else "NOT_AVAILABLE",
        "conclusion": (
            f"TASK-304 revenue risk identification abstained for {project_name}: "
            "more evidence is required before assigning a risk level."
        ),
        "node_status": "abstained",
        "judgment_status": "PENDING_REVIEW",
        "confidence_level": "low",
    }
