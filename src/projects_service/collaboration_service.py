"""Collaboration application policy. All SQL and HTTP remain behind injected ports."""

import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from projects_service.access_domain import OWNER, AccessError, Member, utc
from projects_service.access_service import AccessService
from projects_service.collaboration_domain import (
    AllocationDraft,
    MemberDraft,
    RoleDraft,
    RolePatch,
    TeamDraft,
    TeamInvite,
    TeamLink,
    TeamMemberDraft,
    TeamPatch,
)
from projects_service.collaboration_repository import CollaborationRepository
from projects_service.domain import Project


def unavailable(*args: Any) -> Any:
    raise AccessError(503, "Dependency temporarily unavailable")


class CollaborationService:
    def __init__(
        self,
        repository: CollaborationRepository,
        access: AccessService,
        clock: Callable[[], datetime],
    ) -> None:
        self.repository = repository
        self.access = access
        self.clock = clock
        self.identity_active: Callable[[UUID], bool] = unavailable
        self.backlog_summary: Callable[[UUID], dict[str, Any]] = unavailable
        self.backlog_items: Callable[[UUID], list[dict[str, Any]]] = unavailable
        self.directory: Callable[[], list[dict[str, Any]]] = unavailable
        self.profile: Callable[[UUID], dict[str, Any] | None] = unavailable

    def require_active(self, user: UUID) -> None:
        if not self.identity_active(user):
            raise AccessError(422, "User unavailable")

    def role(
        self, user: UUID, project_id: UUID, key: str | None, draft: RoleDraft | RolePatch | None
    ) -> dict[str, Any] | None:
        with self.repository.locked_project(project_id) as row:
            actor = self.access.require(row, user, "project:roles:manage")
            assert row is not None
            self.access.writable(row, administrative=True, revocation=draft is None)
            existing = {r["key"]: r for r in self.repository.definitions(project_id)}
            if key and not key.startswith("custom:"):
                raise AccessError(409, "Fixed role is protected")
            if key and key not in existing:
                raise AccessError(404, "Role unavailable")
            if draft is None:
                assert key is not None
                if self.repository.role_linked(project_id, key):
                    raise AccessError(409, "Role is in use")
                self.repository.role_delete(project_id, key)
                result = None
            else:
                values = draft.model_dump(exclude_unset=True, exclude_none=True)
                permissions = values.get(
                    "permissions", existing.get(key or "", {}).get("permissions", [])
                )
                catalog = set(OWNER) - {"project:delete"}
                if (
                    not permissions
                    or len(permissions) != len(set(permissions))
                    or not set(permissions).issubset(catalog)
                    or "project:read" not in permissions
                ):
                    raise AccessError(422, "Invalid project permissions")
                if not set(permissions).issubset(actor.permissions):
                    raise AccessError(403, "Cannot delegate unavailable privileges")
                values["permissions"] = sorted(permissions)
                result = self.repository.role_save(
                    project_id, key or "custom:" + str(uuid4()), values
                )
            self.repository.change_state(project_id, user, {}, "access.role.changed")
        return result

    def add_member(self, user: UUID, project_id: UUID, draft: MemberDraft) -> Member:
        with self.repository.locked_project(project_id) as row:
            self.access.require(row, user, "project:members:manage")
            assert row is not None
            self.access.writable(row, administrative=True)
            self.access.validate_roles(row, user, draft)
            self.access.validate_expiry(draft.expires_at)
            if row.owner_id == draft.user_id or self.repository.member(project_id, draft.user_id):
                raise AccessError(409, "Member already exists")
            self.require_active(draft.user_id)
            result = Member(
                user_id=draft.user_id,
                roles=list(draft.roles),
                expires_at=draft.expires_at,
                role_grants=self.access.grants(draft, draft.expires_at),
            )
            self.repository.deny(project_id, draft.user_id, False)
            self.repository.add_member(project_id, result)
            self.repository.change_state(project_id, user, {}, "access.member.added")
        return result

    def eligibility(self, user: UUID, project_id: UUID, target: UUID) -> dict[str, Any]:
        row = self.repository.project(project_id)
        self.access.require(row, user, "project:members:read")
        assert row is not None
        access = self.access.access_for(row, target)
        active = self.identity_active(target) if access.permissions else False
        return {
            "user_id": target,
            "eligible": bool(active and "project:read" in access.permissions),
            "roles": access.roles if active else [],
            "permissions": access.permissions if active else [],
        }

    def team_access(self, user: UUID, team: dict[str, Any] | None, *, manage: bool = False) -> bool:
        if team is None:
            raise AccessError(404, "Team unavailable")
        members = self.repository.team_members(team["id"])
        member = next((m for m in members if m["user_id"] == user), None)
        if member is None and team["owner_id"] != user:
            raise AccessError(404, "Team unavailable")
        manager = team["owner_id"] == user or bool(member and member["is_manager"])
        if manage and not manager:
            raise AccessError(403, "Insufficient team permissions")
        return manager

    def create_team(self, user: UUID, draft: TeamDraft) -> dict[str, Any]:
        team_id = uuid4()
        result = self.repository.team_save(
            team_id,
            {"owner_id": user, "created_at": utc(self.clock()), "version": 1, **draft.model_dump()},
        )
        self.repository.team_member_save(team_id, user, {"is_manager": True})
        self.repository.commit()
        return result

    def get_team(self, user: UUID, team_id: UUID) -> dict[str, Any]:
        team = self.repository.team(team_id)
        manager = self.team_access(user, team)
        assert team is not None
        if not manager:
            team = {**team, "cost_center": None}
        return team

    def list_teams(self, user: UUID, limit: int, offset: int) -> dict[str, Any]:
        teams = [self.get_team(user, r["id"]) for r in self.repository.teams(user)]
        return {
            "items": teams[offset : offset + limit],
            "total": len(teams),
            "limit": limit,
            "offset": offset,
        }

    def patch_team(self, user: UUID, team_id: UUID, draft: TeamPatch) -> dict[str, Any]:
        with self.repository.locked_team(team_id) as team:
            self.team_access(user, team, manage=True)
            result = self.repository.team_save(team_id, draft.model_dump(exclude_unset=True))
        return result

    def team_members(self, user: UUID, team_id: UUID) -> dict[str, Any]:
        manager = self.team_access(user, self.repository.team(team_id))
        members = self.repository.team_members(team_id)
        if not manager:
            members = [
                {key: value for key, value in m.items() if key not in {"hourly_rate", "currency"}}
                for m in members
            ]
        return {"items": members, "total": len(members)}

    def team_member(
        self, user: UUID, team_id: UUID, target: UUID, draft: TeamMemberDraft | None
    ) -> dict[str, Any] | None:
        with self.repository.locked_team(team_id) as team:
            self.team_access(user, team, manage=True)
            assert team is not None
            if team["owner_id"] == target:
                raise AccessError(409, "Team owner is protected")
            if draft is not None:
                self.require_active(target)
            result = self.repository.team_member_save(
                team_id, target, draft.model_dump(exclude={"user_id"}) if draft else None
            )
            self.repository.team_save(team_id, {})
        return result

    def invite_team(self, user: UUID, team_id: UUID, draft: TeamInvite) -> dict[str, Any]:
        with self.repository.locked_team(team_id) as team:
            self.team_access(user, team, manage=True)
            if any(m["user_id"] == draft.user_id for m in self.repository.team_members(team_id)):
                raise AccessError(409, "Team member already exists")
            self.require_active(draft.user_id)
            code = secrets.token_urlsafe(32)
            invitation = {
                "id": uuid4(),
                "team_id": team_id,
                **draft.model_dump(),
                "code_hash": sha256(code.encode()).hexdigest(),
                "code_expires_at": utc(self.clock()) + timedelta(days=7),
                "status": "pending",
            }
            self.repository.team_invitation_save(invitation)
        return {key: value for key, value in invitation.items() if key != "code_hash"} | {
            "code": code
        }

    def consume_team(self, user: UUID, code: str, accept: bool) -> dict[str, Any] | None:
        digest = sha256(code.encode()).hexdigest()
        candidate = self.repository.team_invitation(digest)
        if not candidate:
            raise AccessError(404, "Invitation unavailable")
        with self.repository.locked_team(candidate["team_id"]) as team:
            invite = self.repository.team_invitation(digest)
            if (
                team is None
                or invite is None
                or invite["user_id"] != user
                or invite["status"] != "pending"
                or utc(invite["code_expires_at"]) <= utc(self.clock())
                or any(
                    m["user_id"] == user for m in self.repository.team_members(candidate["team_id"])
                )
            ):
                raise AccessError(404, "Invitation unavailable")
            self.repository.consume_team_invitation(
                invite["id"], "accepted" if accept else "declined"
            )
            if accept:
                self.repository.team_member_save(
                    team["id"], user, {"is_manager": invite["is_manager"]}
                )
                self.repository.team_save(team["id"], {})
            result = team if accept else None
        return result

    def project_teams(self, user: UUID, project_id: UUID) -> dict[str, Any]:
        self.access.require(self.repository.project(project_id), user, "project:members:read")
        teams = self.repository.project_teams(project_id)
        return {"items": teams, "total": len(teams)}

    def link_team(
        self, user: UUID, project_id: UUID, team_id: UUID, draft: TeamLink | None
    ) -> dict[str, Any] | None:
        with self.repository.locked_project(project_id) as row:
            self.access.require(row, user, "project:teams:manage")
            assert row is not None
            self.access.writable(row, administrative=True, revocation=draft is None)
            if draft:
                self.team_access(user, self.repository.team(team_id), manage=True)
                self.access.validate_roles(row, user, draft)
                self.access.validate_expiry(draft.expires_at)
            result = self.repository.link_team(
                project_id,
                team_id,
                {"roles": draft.roles, "expires_at": draft.expires_at} if draft else None,
            )
            self.repository.change_state(
                project_id, user, {}, "access.team.linked" if draft else "access.team.unlinked"
            )
        return result

    def lease(self, user: UUID, project_id: UUID, operation: UUID) -> dict[str, Any]:
        with self.repository.locked_project(project_id) as row:
            actor = self.access.require(row, user)
            assert row is not None
            if not set(actor.permissions) & {
                "backlog:create",
                "backlog:update",
                "backlog:update_status",
                "backlog:reorder",
            }:
                raise AccessError(403, "Insufficient project permissions")
            self.access.writable(row)
            existing = self.repository.lease(project_id, operation)
            if existing:
                if existing["actor_id"] != user or existing["released"]:
                    raise AccessError(409, "Write operation already completed")
                lease_id = existing["id"]
            else:
                lease_id = self.repository.lease_add(project_id, user, operation)
        return {"lease_id": lease_id, "project_id": project_id}

    def release_lease(self, user: UUID, project_id: UUID, lease_id: UUID) -> None:
        with self.repository.locked_project(project_id):
            if not self.repository.lease_release(project_id, user, lease_id):
                raise AccessError(404, "Write lease unavailable")

    def delete_project(self, user: UUID, project_id: UUID) -> bool:
        with self.repository.locked_project(project_id) as row:
            if row is None or "project:read" not in self.access.access_for(row, user).permissions:
                return False
            self.access.require(row, user, "project:delete")
            if (
                self.repository.frozen(project_id)
                or self.repository.active_leases(project_id)
                or self.repository.relevant(project_id)
            ):
                raise AccessError(409, "Project contains relevant data or active writes")
            self.repository.freeze(project_id, True)
        try:
            summary = self.backlog_summary(project_id)
            with self.repository.locked_project(project_id) as row:
                self.access.require(row, user, "project:delete")
                if (
                    summary["total"]
                    or self.repository.relevant(project_id)
                    or self.repository.active_leases(project_id)
                ):
                    raise AccessError(409, "Project contains relevant data")
                self.repository.delete_project(project_id, user)
            return True
        except Exception:
            with self.repository.locked_project(project_id) as row:
                if row:
                    self.repository.freeze(project_id, False)
            raise

    def transfer(self, user: UUID, project_id: UUID, target: UUID, version: int) -> Project:
        with self.repository.locked_project(project_id) as row:
            actor = self.access.require(row, user)
            assert row is not None
            if not actor.is_owner:
                raise AccessError(403, "Owner required")
            self.access.writable(row, administrative=True)
            if row.version != version:
                raise AccessError(409, "Project version conflict")
            if target == user or not self.access.access_for(row, target).permissions:
                raise AccessError(422, "New owner must be an authorized member")
            self.require_active(target)
            self.repository.delete_member(project_id, target)
            self.repository.deny(project_id, target, False)
            self.repository.add_member(
                project_id, Member(user_id=user, roles=["project_manager"], expires_at=None)
            )
            result = self.repository.change_state(
                project_id, user, {"owner_id": target}, "project.transferred"
            )
        return self.access.project(result, user)

    def allocation(
        self, user: UUID, project_id: UUID, draft: AllocationDraft | None
    ) -> dict[str, Any]:
        if draft is None:
            self.access.require(self.repository.project(project_id), user, "project:members:manage")
            rows = self.repository.allocations(project_id=project_id)
            return {"items": rows, "total": len(rows)}
        with self.repository.locked_project(project_id) as row:
            self.access.require(row, user, "project:members:manage")
            assert row is not None
            self.access.writable(row)
            if not self.access.access_for(row, draft.user_id).permissions:
                raise AccessError(422, "Allocation member unavailable")
            self.require_active(draft.user_id)
            self.repository.lock_capacity(draft.user_id)
            profile = self.profile(draft.user_id)
            if profile is not None:
                allocated = sum(
                    (
                        Decimal(a["weekly_hours"])
                        for a in self.active_allocations(draft.user_id)
                        if a["project_id"] != project_id
                    ),
                    Decimal(0),
                )
                if allocated + Decimal(draft.weekly_hours) > Decimal(
                    profile["weekly_availability_hours"]
                ):
                    raise AccessError(409, "Allocation exceeds known capacity")
            result = self.repository.allocation_save(
                project_id, draft.user_id, draft.model_dump(exclude={"user_id", "is_manager"})
            )
            self.repository.change_state(project_id, user, {}, "project.allocation.updated")
        return result

    def allocations_me(self, user: UUID) -> dict[str, Any]:
        allocations = self.active_allocations(user)
        teams = [self.get_team(user, team["id"]) for team in self.repository.teams(user)]
        capacities = [
            Decimal(m["weekly_hours"])
            for t in teams
            for m in self.repository.team_members(t["id"])
            if m["user_id"] == user and m["weekly_hours"] is not None
        ]
        profile = self.profile(user)
        capacity = (
            Decimal(profile["weekly_availability_hours"])
            if profile
            else min(capacities)
            if capacities
            else None
        )
        return {
            "projects": allocations,
            "teams": teams,
            "weekly_availability_hours": str(capacity) if capacity is not None else None,
            "total_allocated_hours": str(
                sum((Decimal(a["weekly_hours"]) for a in allocations), Decimal(0))
            ),
        }

    def summary(self, user: UUID, project_id: UUID) -> dict[str, Any]:
        project = self.access.get(user, project_id)
        self.access.require(project, user)
        try:
            backlog = self.backlog_summary(project_id)
        except AccessError:
            backlog = None
        return {
            "project": project,
            "teams": self.repository.project_teams(project_id),
            "backlog": backlog,
            "backlog_available": backlog is not None,
        }

    def notifications(self, user: UUID, limit: int, offset: int) -> dict[str, Any]:
        return self.repository.notifications(user, limit, offset)

    def read_notification(self, user: UUID, notification_id: UUID) -> dict[str, Any]:
        result = self.repository.read_notification(user, notification_id, utc(self.clock()))
        if result is None:
            raise AccessError(404, "Notification unavailable")
        return result

    def active_allocations(self, user: UUID) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for allocation in self.repository.allocations(user=user):
            project = self.repository.project(allocation["project_id"])
            if (
                project is not None
                and project.status in {"planned", "active"}
                and not project.archived
                and "project:read" in self.access.access_for(project, user).permissions
            ):
                result.append(allocation)
        return result

    def observe_access(self, user: UUID, project_id: UUID) -> None:
        project = self.repository.project(project_id)
        if (
            project is not None
            and "project:read" in self.access.access_for(project, user).permissions
        ):
            self.repository.observe_activity(project, user, utc(self.clock()))
