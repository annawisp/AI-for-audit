"""Project Context MVP (TASK-201) schemas.

Project Context is the project-level minimum information that every audit
capability consumes as unified context.  MVP 1.0 keeps five core sections:

- basic_info     基础信息
- audit_period   审计期间
- materiality    重要性
- revenue_model  收入模式
- contracts      合同

Revenue details / customer list / supplier list / receivables / bank
statements belong to MVP 2.0 optional inputs and are intentionally not part
of the MVP payload schema (versioned JSON snapshots keep future schema
evolution safe).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class BasicInfo(BaseModel):
    """MVP core section: basic information about the audited entity."""

    entity_name: str | None = Field(default=None, max_length=300)
    industry: str | None = Field(default=None, max_length=200)
    currency: str | None = Field(default=None, max_length=8)
    reporting_framework: str | None = Field(default=None, max_length=200)
    consolidated: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class AuditPeriod(BaseModel):
    """MVP core section: audited reporting period (an inclusive range)."""

    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_range(self) -> "AuditPeriod":
        if self.start_date > self.end_date:
            raise ValueError("start_date cannot be later than end_date")
        return self


class Materiality(BaseModel):
    """MVP core section: planning materiality judgments (auditor input)."""

    overall_amount: float | None = Field(default=None, ge=0)
    overall_basis: str | None = Field(default=None, max_length=200)
    performance_amount: float | None = Field(default=None, ge=0)
    trivial_amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    determined_by: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class RevenueStream(BaseModel):
    """One revenue stream of the audited business model."""

    name: str = Field(min_length=1, max_length=200)
    recognition_basis: str | None = Field(default=None, max_length=200)
    is_primary: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class RevenueModel(BaseModel):
    """MVP core section: how the entity earns revenue (recognition context)."""

    description: str | None = Field(default=None, max_length=2000)
    revenue_streams: list[RevenueStream] = Field(default_factory=list)


class ContractEntry(BaseModel):
    """A contract in scope of the engagement.

    MVP supports two shapes (decision 1c):
    - document reference: ``document_id`` points to an uploaded document;
      element extraction itself belongs to TASK-302 and is not performed here.
    - manual summary: free-text fields recorded by the auditor without parsing.
    At least one of ``document_id`` / ``title`` is required.
    """

    document_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=300)
    contract_no: str | None = Field(default=None, max_length=200)
    counterparty: str | None = Field(default=None, max_length=300)
    signed_date: date | None = None
    effective_start: date | None = None
    effective_end: date | None = None
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_entry(self) -> "ContractEntry":
        if not self.document_id and not self.title:
            raise ValueError("contract entry requires document_id or title")
        if (
            self.effective_start
            and self.effective_end
            and self.effective_start > self.effective_end
        ):
            raise ValueError("effective_start cannot be later than effective_end")
        return self


class ProjectContextPayload(BaseModel):
    """Full Project Context payload written as a versioned JSON snapshot.

    Every update replaces the whole payload and creates a new version; omit a
    section (or pass an empty object) to mark it as not provided for that
    version.  Missing data is never interpreted as "procedure not performed".
    """

    basic_info: BasicInfo = Field(default_factory=BasicInfo)
    audit_period: AuditPeriod | None = None
    materiality: Materiality = Field(default_factory=Materiality)
    revenue_model: RevenueModel = Field(default_factory=RevenueModel)
    contracts: list[ContractEntry] = Field(default_factory=list)


class ProjectContextWrite(BaseModel):
    """Request body: new full snapshot plus traceability metadata."""

    payload: ProjectContextPayload
    changed_by: str | None = Field(default=None, max_length=100)
    change_reason: str | None = Field(default=None, max_length=500)


class ProjectContextVersionMeta(BaseModel):
    """Version metadata (payload excluded) for list responses."""

    version_id: str
    project_id: str
    version: int
    changed_by: str | None
    change_reason: str | None
    changed_sections: list[str]
    is_current: bool
    created_at: datetime


class ProjectContextVersionResponse(BaseModel):
    """One immutable version snapshot of the project context."""

    version_id: str
    project_id: str
    version: int
    payload: ProjectContextPayload
    changed_by: str | None
    change_reason: str | None
    changed_sections: list[str]
    is_current: bool
    created_at: datetime
    trace_id: str


class ProjectContextVersionListResponse(BaseModel):
    items: list[ProjectContextVersionMeta]
    trace_id: str


SectionStatus = Literal["provided", "partial", "not_provided"]


class CoreSectionReadiness(BaseModel):
    """Availability of one MVP core section."""

    section: str
    label: str
    status: SectionStatus
    required_for_start: bool
    present_fields: list[str]
    missing_core_fields: list[str]


class ExtendedSectionReadiness(BaseModel):
    """MVP 2.0 optional input: not stored yet, never blocks execution."""

    section: str
    label: str
    scope: Literal["mvp_2_0_optional"]
    status: Literal["not_provided"]
    note: str


class ProjectContextReadinessResponse(BaseModel):
    """Whether the project can start with the current context version."""

    project_id: str
    context_version: int | None
    minimal_requirements_met: bool
    minimal_required_sections: list[str]
    core_sections: list[CoreSectionReadiness]
    extended_sections: list[ExtendedSectionReadiness]
    missing_does_not_block: bool
    summary: str
    trace_id: str
