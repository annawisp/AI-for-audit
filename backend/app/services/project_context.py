"""Project Context MVP (TASK-201) domain logic.

Pure functions only (no FastAPI / repository imports) so they stay unit
testable and reusable by the readiness endpoint, future procedure state
machines, and quality gates.

Readiness vocabulary for a section is one of:

- provided       section carries its core fields (e.g. basic_info.entity_name)
- partial        section started but core fields are missing
- not_provided   section absent or empty — never interpreted as "the auditor
                 did not perform the procedure"
"""

import json
from typing import Any

CORE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("basic_info", "基础信息"),
    ("audit_period", "审计期间"),
    ("materiality", "重要性"),
    ("revenue_model", "收入模式"),
    ("contracts", "合同"),
)

EXTENDED_SECTIONS: tuple[tuple[str, str], ...] = (
    ("revenue_details", "收入明细"),
    ("customer_list", "客户名单"),
    ("supplier_list", "供应商名单"),
    ("receivables", "应收账款"),
    ("bank_statements", "银行流水"),
)

# A project can start with basic information alone; contracts and the other
# core sections are useful but must not block project start.
MINIMAL_REQUIRED_SECTIONS: tuple[str, ...] = ("basic_info",)

EXTENDED_NOTE = "MVP 2.0 可选输入，当前系统不消费；未提供不影响 MVP 核心段与项目启动"


def is_empty_value(value: Any) -> bool:
    """True when a payload value carries no usable content."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, dict):
        return all(is_empty_value(item) for item in value.values())
    if isinstance(value, list):
        return len(value) == 0
    return False


def present_fields(section_value: Any) -> list[str]:
    """Names of non-empty fields inside a section object."""
    if not isinstance(section_value, dict):
        return []
    return [key for key, value in section_value.items() if not is_empty_value(value)]


def non_empty_sections(payload: dict[str, Any]) -> list[str]:
    """Core sections of a payload that carry at least some content."""
    return [section for section, _ in CORE_SECTIONS if not is_empty_value(payload.get(section))]


def _core_missing_when_empty(section: str) -> list[str]:
    """Fields whose presence would make the section count as provided."""
    if section == "basic_info":
        return ["entity_name"]
    if section == "audit_period":
        return ["start_date", "end_date"]
    if section == "materiality":
        return ["overall_amount", "performance_amount"]
    return []


def evaluate_core_section(
    section: str, payload: dict[str, Any]
) -> tuple[str, list[str], list[str]]:
    """Return (status, present_fields, missing_core_fields) for a core section."""
    value = payload.get(section)
    if section == "contracts":
        entries = value if isinstance(value, list) else []
        if entries:
            return "provided", [], []
        return "not_provided", [], []

    if is_empty_value(value):
        return "not_provided", [], _core_missing_when_empty(section)

    fields = present_fields(value)
    if section == "basic_info":
        if "entity_name" in fields:
            return "provided", fields, []
        return "partial", fields, ["entity_name"]
    if section == "audit_period":
        missing = [name for name in ("start_date", "end_date") if name not in fields]
        if not missing:
            return "provided", fields, []
        return "partial", fields, missing
    if section == "materiality":
        if "overall_amount" in fields or "performance_amount" in fields:
            return "provided", fields, []
        return (
            "partial",
            fields,
            [name for name in ("overall_amount", "performance_amount") if name not in fields],
        )
    if section == "revenue_model":
        return ("provided", fields, []) if fields else ("not_provided", [], [])
    raise ValueError(f"Unknown core section: {section}")


def seed_initial_payload(payload: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    """Seed context version 1 from project master data.

    Only fills fields the client left empty, so the stored snapshot remains a
    single source of truth for capabilities instead of duplicating the
    projects table.  Seeding happens once (version 1); later versions store
    exactly what the client submits.
    """
    seeded = json.loads(json.dumps(payload))

    client_name = project.get("client_name")
    if client_name and is_empty_value(seeded.get("basic_info", {}).get("entity_name")):
        basic_info = dict(seeded.get("basic_info") or {})
        basic_info["entity_name"] = client_name
        seeded["basic_info"] = basic_info

    period_start = project.get("audit_period_start")
    period_end = project.get("audit_period_end")
    if period_start and period_end and is_empty_value(seeded.get("audit_period")):
        seeded["audit_period"] = {"start_date": period_start, "end_date": period_end}

    return seeded


def _summary_text(core_sections: list[dict[str, Any]], minimal_met: bool) -> str:
    missing = [
        f"{item['label']}({item['status']})"
        for item in core_sections
        if item["status"] != "provided"
    ]
    missing_text = "、".join(missing) if missing else "无"
    met_text = "已满足" if minimal_met else "未满足"
    return (
        f"最小启动条件（基础信息）{met_text}；未提供或部分提供的核心段：{missing_text}。"
        "缺失资料不会被系统解释为审计师未执行程序；后续审计能力将按证据充分性自行 Abstention，"
        "缺少扩展数据不阻塞项目运行。"
    )


def build_readiness(
    project_id: str, context_row: dict[str, Any] | None
) -> dict[str, Any]:
    """Build the readiness report payload from the current context row (or none)."""
    payload: dict[str, Any] = {}
    version: int | None = None
    if context_row is not None:
        payload = json.loads(context_row["payload_json"])
        version = int(context_row["version"])

    core_sections: list[dict[str, Any]] = []
    for section, label in CORE_SECTIONS:
        status, fields, missing = evaluate_core_section(section, payload)
        core_sections.append(
            {
                "section": section,
                "label": label,
                "status": status,
                "required_for_start": section in MINIMAL_REQUIRED_SECTIONS,
                "present_fields": fields,
                "missing_core_fields": missing,
            }
        )

    extended_sections = [
        {
            "section": section,
            "label": label,
            "scope": "mvp_2_0_optional",
            "status": "not_provided",
            "note": EXTENDED_NOTE,
        }
        for section, label in EXTENDED_SECTIONS
    ]

    minimal_met = all(
        next(
            item for item in core_sections if item["section"] == required
        )["status"]
        == "provided"
        for required in MINIMAL_REQUIRED_SECTIONS
    )

    return {
        "project_id": project_id,
        "context_version": version,
        "minimal_requirements_met": minimal_met,
        "minimal_required_sections": list(MINIMAL_REQUIRED_SECTIONS),
        "core_sections": core_sections,
        "extended_sections": extended_sections,
        "missing_does_not_block": True,
        "summary": _summary_text(core_sections, minimal_met),
    }
