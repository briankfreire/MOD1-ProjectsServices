from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProjectDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    objective: str = Field(default="", max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProjectPatch(BaseModel):
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


class Project(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str
    objective: str = ""
    created_at: datetime


class ProjectPage(BaseModel):
    items: list[Project]
    total: int
    limit: int
    offset: int
