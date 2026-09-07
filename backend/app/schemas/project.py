from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    audit_period_start: date | None = None
    audit_period_end: date | None = None

    @model_validator(mode="after")
    def validate_audit_period(self) -> "ProjectCreate":
        if (
            self.audit_period_start
            and self.audit_period_end
            and self.audit_period_start > self.audit_period_end
        ):
            raise ValueError("audit_period_start cannot be later than audit_period_end")
        return self


class ProjectResponse(BaseModel):
    project_id: str
    name: str
    client_name: str | None
    audit_period_start: date | None
    audit_period_end: date | None
    status: Literal["active", "archived"]
    created_at: datetime
    updated_at: datetime
    trace_id: str


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    trace_id: str
