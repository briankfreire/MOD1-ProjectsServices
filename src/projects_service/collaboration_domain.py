"""Validated collaboration inputs; independent of HTTP and persistence."""

from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from projects_service.access_domain import InvitationDraft, MembershipPatch


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class RoleDraft(Input):
    name: str = Field(min_length=1, max_length=120)
    permissions: list[str] = Field(min_length=1, max_length=30)


class RolePatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    permissions: list[str] | None = Field(default=None, min_length=1, max_length=30)


class TeamDraft(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    cost_center: str | None = Field(default=None, max_length=120)


class TeamPatch(Input):
    name: str = Field(default="", min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    cost_center: str | None = Field(default=None, max_length=120)


class TeamMemberDraft(Input):
    user_id: UUID = Field(strict=False)
    is_manager: bool = False
    weekly_hours: str | None = None
    hourly_rate: str | None = None
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")

    @field_validator("weekly_hours", "hourly_rate")
    @classmethod
    def decimal_value(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                amount = Decimal(value)
                if (
                    not amount.is_finite()
                    or amount < 0
                    or amount > Decimal("999999999")
                    or amount != amount.quantize(Decimal("0.01"))
                ):
                    raise ValueError("Invalid value")
            except InvalidOperation:
                raise ValueError("Invalid value") from None
        return value

    @model_validator(mode="after")
    def values_coherent(self) -> "TeamMemberDraft":
        if self.weekly_hours is not None and Decimal(self.weekly_hours) > 168:
            raise ValueError("Invalid capacity")
        if (self.hourly_rate is None) != (self.currency is None):
            raise ValueError("Rate requires currency")
        return self


class TeamInvite(Input):
    user_id: UUID = Field(strict=False)
    is_manager: bool = False


class TeamLink(MembershipPatch):
    team_id: UUID = Field(strict=False)


class MemberDraft(InvitationDraft):
    pass


class LeaseDraft(Input):
    operation_id: UUID = Field(strict=False)


class AllocationDraft(TeamMemberDraft):
    weekly_hours: str
    is_manager: Literal[False] = False


class RecommendationDraft(Input):
    kind: Literal["roles", "access_revocation", "teams", "skills_map", "training"]
    constraints: dict[str, str | int | bool] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def inactivity_window(self) -> "RecommendationDraft":
        if self.kind == "access_revocation" and "unused_days" in self.constraints:
            days = self.constraints["unused_days"]
            if type(days) is not int or not 1 <= days <= 3650:
                raise ValueError("Invalid inactivity window")
        return self


class EmptyAction(Input):
    pass
