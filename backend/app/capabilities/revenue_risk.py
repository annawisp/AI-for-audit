from __future__ import annotations

import json
from typing import Any

RULES_VERSION = "task304-rule-based-v1"


def identify_revenue_risks(
    *,
    project: dict[str, Any],
    contract_evidence: dict[str, Any] | None,
    revenue_recognition_evidence: dict[str, Any] | None,
    revenue_records: list[Any] | None,
    enable_semantic_judgment: bool = False,
) -> dict[str, Any]:
    records = revenue_records or []
    recognition_value = (
        revenue_recognition_evidence.get("extracted_value")
        if revenue_recognition_evidence
        else None
    )
    text = "\n".join(
        part
        for part in [
            _stringify(contract_evidence.get("extracted_value") if contract_evidence else None),
            _stringify(recognition_value),
            _stringify([_model_dump(record) for record in records]),
        ]
        if part
    ).lower()

    signals: list[dict[str, Any]] = []
    limitations: list[str] = []

    if contract_evidence is None and revenue_recognition_evidence is None:
        limitations.append("No upstream TASK-302 or TASK-303 evidence was provided.")
        signals.append(
            _signal(
                "insufficient_evidence",
                "Insufficient revenue evidence",
                "MEDIUM",
                "REQUIRES_REVIEW",
                "No upstream evidence is available for revenue-risk identification.",
                "input",
            )
        )

    obligation_keywords = ["multiple", "多项", "多个", "履约义务", "allocation", "分摊"]
    if any(keyword in text for keyword in obligation_keywords):
        signals.append(
            _signal(
                "multiple_obligation_allocation",
                "Multiple obligation allocation risk",
                "HIGH",
                "REQUIRES_REVIEW",
                "Evidence indicates multiple obligations or allocation-sensitive terms.",
                "contract_evidence",
            )
        )

    timing_keywords = ["acceptance", "验收", "milestone", "里程碑", "cutoff", "截止"]
    if any(keyword in text for keyword in timing_keywords):
        signals.append(
            _signal(
                "cutoff_acceptance",
                "Cut-off and acceptance risk",
                "MEDIUM",
                "REQUIRES_REVIEW",
                "Evidence includes acceptance, milestone, or cut-off wording.",
                "contract_evidence",
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

    high = any(signal["risk_level"] == "HIGH" for signal in signals)
    review = any(signal["status"] == "REQUIRES_REVIEW" for signal in signals)
    evidence_count = (
        int(contract_evidence is not None)
        + int(revenue_recognition_evidence is not None)
        + int(bool(records))
    )
    coverage_ratio = round(evidence_count / 3, 2)
    overall = "HIGH" if high else "MEDIUM" if review else "LOW"
    status = "REQUIRES_REVIEW" if review else "COMPLETED"
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
        f"overall risk is {overall}."
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
        "node_status": "partial" if review else "ready",
        "judgment_status": "PENDING_REVIEW" if review else "AI_GENERATED",
        "confidence_level": "medium" if review else "high",
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
    risk_level: str,
    status: str,
    rationale: str,
    source: str,
) -> dict[str, str]:
    return {
        "signal_id": signal_id,
        "name": name,
        "risk_level": risk_level,
        "status": status,
        "rationale": rationale,
        "source": source,
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


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)
