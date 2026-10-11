from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class Project(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str
    created_at: datetime


class ProjectPage(BaseModel):
    items: list[Project]
    total: int
    limit: int
    offset: int
