"""Strict provider output and type-specific suggestions."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1, max_length=500)]


class AIResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1, max_length=2000)
    justification: str = Field(min_length=1, max_length=4000)
    evidence: list[Text] = Field(min_length=1, max_length=50)
    suggestions: list[dict[str, object]] = Field(min_length=1, max_length=50)


def valid_suggestions(
    kind: str,
    suggestions: list[dict[str, object]],
    *,
    users: set[str],
    members: set[str],
    teams: set[str],
    roles: set[str],
    owner: str,
    known_skills: set[str],
) -> bool:
    for suggestion in suggestions:
        if kind == "roles":
            if (
                set(suggestion) != {"user_id", "roles"}
                or not isinstance(suggestion["user_id"], str)
                or suggestion["user_id"] not in users
            ):
                return False
            assigned = suggestion["roles"]
            if (
                not isinstance(assigned, list)
                or not assigned
                or len(assigned) > 50
                or any(not isinstance(role, str) or role not in roles for role in assigned)
                or len(set(assigned)) != len(assigned)
            ):
                return False
            if suggestion["user_id"] == owner:
                return False
        elif kind == "access_revocation":
            if (
                set(suggestion) != {"user_id", "reason"}
                or not isinstance(suggestion["user_id"], str)
                or suggestion["user_id"] not in members
                or suggestion["user_id"] == owner
                or not isinstance(suggestion["reason"], str)
                or not 1 <= len(suggestion["reason"]) <= 500
            ):
                return False
        elif kind == "teams":
            if set(suggestion) == {"team_id", "roles"}:
                if not isinstance(suggestion["team_id"], str) or suggestion["team_id"] not in teams:
                    return False
            elif set(suggestion) == {"name", "user_ids", "roles"}:
                ids = suggestion["user_ids"]
                if (
                    not isinstance(suggestion["name"], str)
                    or not 1 <= len(suggestion["name"]) <= 120
                    or not isinstance(ids, list)
                    or not ids
                    or len(ids) > 100
                    or any(not isinstance(i, str) or i not in users for i in ids)
                    or len(set(ids)) != len(ids)
                ):
                    return False
            else:
                return False
            assigned = suggestion["roles"]
            if (
                not isinstance(assigned, list)
                or not assigned
                or any(not isinstance(r, str) or r not in roles for r in assigned)
                or len(set(assigned)) != len(assigned)
            ):
                return False
        elif kind == "skills_map":
            if (
                set(suggestion) != {"skill", "user_ids", "gap"}
                or not isinstance(suggestion["skill"], str)
                or suggestion["skill"] not in known_skills
                or type(suggestion["gap"]) is not bool
            ):
                return False
            ids = suggestion["user_ids"]
            if (
                not isinstance(ids, list)
                or len(ids) > 100
                or any(not isinstance(i, str) or i not in users for i in ids)
            ):
                return False
        elif kind == "training":
            if (
                set(suggestion) != {"user_id", "topics"}
                or not isinstance(suggestion["user_id"], str)
                or suggestion["user_id"] not in users
            ):
                return False
            topics = suggestion["topics"]
            if (
                not isinstance(topics, list)
                or not topics
                or len(topics) > 20
                or any(
                    not isinstance(t, str) or not 1 <= len(t) <= 200 or "://" in t for t in topics
                )
            ):
                return False
        else:
            return False
    return True


class WorkItemSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    id: UUID = Field(strict=False)
    project_id: UUID = Field(strict=False)
    kind: Literal["story", "task", "epic"]
    title: str = Field(min_length=1, max_length=200)
    status: Literal["todo", "in_progress", "done"]
    assignee_id: UUID | None = Field(default=None, strict=False)
    version: int = Field(ge=1)
    priority: Literal["high", "medium", "low"] | None = None
    moscow_priority: Literal["must", "should", "could", "wont"] | None = None
    estimate_value: str | None = Field(default=None, max_length=40)
    estimate_unit: Literal["points", "hours"] | None = None
    is_blocked: bool = False
