from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Metadata(BaseModel):
    scope: str = Field(default="", max_length=10000)
    budget_amount: str | None = None
    budget_currency: str = Field(default="BRL", pattern=r"^[A-Z]{3}$")
    tags: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=30
    )
    planned_start: date | None = Field(default=None, strict=False)
    planned_end: date | None = Field(default=None, strict=False)
    technology_stack: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=50
    )
    technical_requirements: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=100
    )
    soft_skills: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=50
    )
    constraints: str = Field(default="", max_length=10000)

    @field_validator("budget_amount")
    @classmethod
    def money(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                amount = Decimal(value)
                if (
                    not amount.is_finite()
                    or amount < 0
                    or amount > Decimal("999999999999.99")
                    or amount != amount.quantize(Decimal("0.01"))
                ):
                    raise ValueError("Invalid amount")
            except InvalidOperation:
                raise ValueError("Invalid amount") from None
        return value

    @model_validator(mode="after")
    def dates(self) -> Self:
        if self.planned_start and self.planned_end and self.planned_end < self.planned_start:
            raise ValueError("Invalid dates")
        return self


class ProjectDraft(Metadata):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    objective: str = Field(default="", max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProjectPatch(Metadata):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    # Only supplied fields reach the mutation; omission never overwrites stored values.
    name: str = Field(default_factory=str, min_length=1, max_length=120)
    description: str = Field(default_factory=str, max_length=2000)
    objective: str = Field(default_factory=str, max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one editable field is required")
        return self


class Project(Metadata):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str
    objective: str = ""
    created_at: datetime
    status: Literal["planned", "active", "suspended", "completed"] = "planned"
    archived: bool = False
    version: int = 1
    permissions: list[str] = Field(default_factory=list)


class ProjectPage(BaseModel):
    items: list[Project]
    total: int
    limit: int
    offset: int


class VersionAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=1)


class LifecycleAction(VersionAction):
    status: Literal["planned", "active", "suspended", "completed"]


class TransferAction(VersionAction):
    user_id: UUID = Field(strict=False)
