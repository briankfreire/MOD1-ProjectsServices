from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

RoleKey = Literal["product_owner", "project_manager", "developer"]
DEVELOPER = frozenset(
    {
        "project:read",
        "project:members:read",
        "backlog:read",
        "backlog:update_status",
    }
)
PRODUCT_OWNER = DEVELOPER | {"project:update", "backlog:create", "backlog:update"}
PROJECT_MANAGER = PRODUCT_OWNER | {"project:members:manage"}
OWNER = PROJECT_MANAGER | {"project:delete"}
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "product_owner": PRODUCT_OWNER,
    "project_manager": PROJECT_MANAGER,
    "developer": DEVELOPER,
}
ROLE_NAMES = {
    "product_owner": "Product Owner",
    "project_manager": "Project Manager",
    "developer": "Developer",
}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Access(BaseModel):
    project_id: UUID
    user_id: UUID
    is_owner: bool
    roles: list[str]
    permissions: list[str]


class Role(BaseModel):
    key: str
    name: str
    permissions: list[str]


class RolePage(BaseModel):
    items: list[Role]


class Member(BaseModel):
    user_id: UUID
    roles: list[str]
    expires_at: datetime | None
    is_owner: bool = False


class MemberPage(BaseModel):
    items: list[Member]
    total: int
    limit: int
    offset: int


class MembershipPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    roles: list[RoleKey] = Field(max_length=3)
    expires_at: AwareDatetime | None = Field(default=None, strict=False)

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, value: list[RoleKey]) -> list[RoleKey]:
        if len(value) != len(set(value)):
            raise ValueError("Duplicate role")
        return sorted(value)

    @field_validator("expires_at", mode="before")
    @classmethod
    def date_input(cls, value: object) -> object:
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("Expected UTC timestamp")
        return value


class InvitationDraft(MembershipPatch):
    user_id: UUID = Field(strict=False)
    roles: list[RoleKey] = Field(min_length=1, max_length=3)


class InvitationCreated(BaseModel):
    id: UUID
    project_id: UUID
    user_id: UUID
    roles: list[str]
    expires_at: datetime | None
    code: str = Field(repr=False)
    code_expires_at: datetime


class InvitationAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    code: str = Field(min_length=1, max_length=512, repr=False)


class AccessError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)
