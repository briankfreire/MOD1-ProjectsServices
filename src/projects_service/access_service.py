from __future__ import annotations

import builtins
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from projects_service.access_domain import (
    OWNER,
    ROLE_NAMES,
    ROLE_PERMISSIONS,
    Access,
    AccessError,
    Invitation,
    InvitationCreated,
    InvitationDraft,
    Member,
    MemberPage,
    MembershipPatch,
    Role,
    RolePage,
    utc,
)
from projects_service.collaboration_repository import CollaborationRepository
from projects_service.domain import Project, ProjectPage, ProjectPatch


class AccessService:
    def __init__(self, repository: CollaborationRepository, clock: Callable[[], datetime]) -> None:
        self.repository = repository
        self.clock = clock

    def access_for(self, row: Project, user: UUID) -> Access:
        owner = row.owner_id == user
        sources = [] if owner else self.repository.sources(row.id, user, self.clock())
        roles = (
            ["owner"] if owner else sorted({role for source in sources for role in source["roles"]})
        )
        definitions = {
            **ROLE_PERMISSIONS,
            **{r["key"]: frozenset(r["permissions"]) for r in self.repository.definitions(row.id)},
        }
        permissions = (
            set(OWNER)
            if owner
            else set().union(*(definitions.get(role, frozenset()) for role in roles))
        )
        return Access(
            project_id=row.id,
            user_id=user,
            is_owner=owner,
            roles=roles,
            permissions=sorted(permissions),
        )

    def require(self, row: Project | None, user: UUID, permission: str = "project:read") -> Access:
        if row is None:
            raise AccessError(404, "Project unavailable")
        access = self.access_for(row, user)
        if "project:read" not in access.permissions:
            raise AccessError(404, "Project unavailable")
        if permission not in access.permissions:
            raise AccessError(403, "Insufficient project permissions")
        return access

    def access(self, user: UUID, project_id: UUID) -> Access:
        return self.require(self.repository.project(project_id), user)

    def project(self, row: Project, user: UUID) -> Project:
        access = self.require(row, user)
        return row.model_copy(update={"permissions": access.permissions})

    def get(self, user: UUID, project_id: UUID) -> Project | None:
        row = self.repository.project(project_id)
        if row is None or "project:read" not in self.access_for(row, user).permissions:
            return None
        return self.project(row, user)

    def list(
        self,
        user: UUID,
        *,
        limit: int,
        offset: int,
        q: str,
        status: str | None = None,
        tag: str | None = None,
        archived: bool = False,
    ) -> ProjectPage:
        rows = self.repository.all_projects(q=q)
        visible = [
            self.project(row, user)
            for row in rows
            if row.archived == archived
            and (status is None or row.status == status)
            and (tag is None or tag in row.tags)
            and "project:read" in self.access_for(row, user).permissions
        ]
        return ProjectPage(
            items=visible[offset : offset + limit], total=len(visible), limit=limit, offset=offset
        )

    def writable(
        self, row: Project, *, administrative: bool = False, revocation: bool = False
    ) -> None:
        if (
            self.repository.frozen(row.id)
            or (row.archived and not revocation)
            or (not administrative and row.status not in {"planned", "active"})
        ):
            raise AccessError(409, "Project is read-only")

    def lifecycle(
        self,
        user: UUID,
        project_id: UUID,
        expected_version: int,
        *,
        status: str | None = None,
        archive: bool | None = None,
    ) -> Project:
        with self.repository.locked_project(project_id) as row:
            self.require(row, user, "project:lifecycle:manage")
            assert row is not None
            if row.version != expected_version or self.repository.frozen(project_id):
                raise AccessError(409, "Project version conflict")
            if archive is not None:
                if row.status != "completed" or row.archived == archive:
                    raise AccessError(409, "Invalid project lifecycle")
                changes: dict[str, object] = {"archived": archive}
                action = "project.archived" if archive else "project.restored"
            else:
                transitions = {
                    "planned": {"active", "suspended"},
                    "active": {"suspended", "completed"},
                    "suspended": {"active", "completed"},
                    "completed": {"active"},
                }
                if row.archived or status not in transitions[row.status]:
                    raise AccessError(409, "Invalid project lifecycle")
                changes = {"status": status}
                action = "project.lifecycle"
            result = self.project(
                self.repository.change_state(project_id, user, changes, action), user
            )
        return result

    def history(
        self, user: UUID, project_id: UUID, limit: int, offset: int, action: str = ""
    ) -> dict[str, object]:
        self.require(self.repository.project(project_id), user, "project:audit:read")
        return self.repository.events(project_id, limit, offset, action)

    def access_v2(self, user: UUID, project_id: UUID) -> dict[str, object]:
        row = self.repository.project(project_id)
        access = self.require(row, user)
        assert row is not None
        return {
            **access.model_dump(),
            "access_version": 2,
            "role_definitions": [{"key": "owner", "name": "Owner", "permissions": sorted(OWNER)}]
            + [
                {"key": key, "name": ROLE_NAMES[key], "permissions": sorted(permissions)}
                for key, permissions in ROLE_PERMISSIONS.items()
            ]
            + [
                {key: value for key, value in r.items() if key != "project_id"}
                for r in self.repository.definitions(project_id)
            ],
            "project_status": row.status,
            "archived": row.archived,
            "version": row.version,
            "origins": [{"type": "owner", "roles": ["owner"]}]
            if access.is_owner
            else self.repository.sources(project_id, user, self.clock()),
        }

    def patch_project(self, user: UUID, project_id: UUID, patch: ProjectPatch) -> Project | None:
        with self.repository.locked_project(project_id) as row:
            if row is None or "project:read" not in self.access_for(row, user).permissions:
                return None
            self.require(row, user, "project:update")
            self.writable(row)
            changed = self.repository.patch_project(
                project_id, user, patch, owner=row.owner_id == user
            )
            result = self.project(changed, user)
        return result

    def delete_project(self, user: UUID, project_id: UUID) -> bool:
        with self.repository.locked_project(project_id) as row:
            if row is None or "project:read" not in self.access_for(row, user).permissions:
                return False
            self.require(row, user, "project:delete")
            self.repository.delete_project(project_id, user)
        return True

    def roles(self, user: UUID, project_id: UUID) -> RolePage:
        self.require(self.repository.project(project_id), user, "project:members:read")
        return RolePage(
            items=[
                Role(key=key, name=ROLE_NAMES[key], permissions=sorted(value))
                for key, value in ROLE_PERMISSIONS.items()
            ]
            + [
                Role(**{key: value for key, value in r.items() if key != "project_id"})
                for r in self.repository.definitions(project_id)
            ]
        )

    def members(self, user: UUID, project_id: UUID, *, limit: int, offset: int) -> MemberPage:
        row = self.repository.project(project_id)
        self.require(row, user, "project:members:read")
        assert row is not None
        owner = Member(user_id=row.owner_id, roles=["owner"], expires_at=None, is_owner=True)
        # Virtual owner is always first, then UUID ordering for durable pagination.
        records = self.repository.members(
            project_id, limit=limit if offset else limit - 1, offset=max(0, offset - 1)
        )
        items = ([owner] if offset == 0 else []) + records
        return MemberPage(
            items=items,
            total=self.repository.member_count(project_id) + 1,
            limit=limit,
            offset=offset,
        )

    def validate_expiry(self, expiry: datetime | None) -> None:
        if expiry is not None and utc(expiry) <= utc(self.clock()):
            raise AccessError(422, "Invalid project input")

    def change_member(
        self, user: UUID, project_id: UUID, target: UUID, patch: MembershipPatch | None
    ) -> Member | None:
        with self.repository.locked_project(project_id) as row:
            self.require(row, user, "project:members:manage")
            assert row is not None
            if target == row.owner_id:
                raise AccessError(409, "Project owner is protected")
            member = self.repository.member(project_id, target)
            inherited = self.repository.sources(project_id, target, self.clock())
            if member is None and not inherited:
                raise AccessError(404, "Member unavailable")
            self.writable(row, administrative=True, revocation=patch is None)
            self.repository.invalidate(project_id, target)
            if patch is None:
                self.repository.delete_member(project_id, target)
                self.repository.deny(project_id, target, True)
                result = None
            else:
                assert member is not None
                self.validate_roles(row, user, patch)
                if "expires_at" in patch.model_fields_set:
                    self.validate_expiry(patch.expires_at)
                    member.expires_at = utc(patch.expires_at) if patch.expires_at else None
                member.roles = list(patch.roles)
                member.role_grants = self.grants(patch, member.expires_at)
                self.repository.update_member(project_id, member)
                result = member
            self.repository.change_state(
                project_id,
                user,
                {},
                "access.member.removed" if patch is None else "access.member.updated",
            )
        return result

    def invite(self, user: UUID, project_id: UUID, draft: InvitationDraft) -> InvitationCreated:
        with self.repository.locked_project(project_id) as row:
            self.require(row, user, "project:members:manage")
            assert row is not None
            self.writable(row, administrative=True)
            self.validate_roles(row, user, draft)
            if draft.user_id == row.owner_id or self.repository.member(project_id, draft.user_id):
                raise AccessError(409, "Member already exists")
            self.validate_expiry(draft.expires_at)
            code = secrets.token_urlsafe(32)
            expiry = utc(draft.expires_at) if draft.expires_at else None
            code_expiry = utc(self.clock()) + timedelta(days=7)
            invitation = Invitation(
                id=uuid4(),
                project_id=project_id,
                user_id=draft.user_id,
                roles=list(draft.roles),
                expires_at=expiry,
                code_expires_at=code_expiry,
                status="pending",
                role_grants=self.grants(draft, expiry),
            )
            self.repository.add_invitation(invitation, sha256(code.encode()).hexdigest())
            result = InvitationCreated(
                id=invitation.id,
                project_id=project_id,
                user_id=draft.user_id,
                roles=list(draft.roles),
                expires_at=expiry,
                code=code,
                code_expires_at=code_expiry,
                role_grants=invitation.role_grants,
            )
            self.repository.change_state(project_id, user, {}, "access.invitation.created")
        return result

    def consume(self, user: UUID, code: str, *, accept: bool) -> Access | None:
        code_hash = sha256(code.encode()).hexdigest()
        candidate = self.repository.invitation(code_hash)
        unavailable = AccessError(404, "Invitation unavailable")
        if candidate is None:
            raise unavailable
        project_id = candidate.project_id
        with self.repository.locked_project(project_id) as row:
            invitation = self.repository.invitation(code_hash)
            now = utc(self.clock())
            if (
                row is None
                or invitation is None
                or invitation.user_id != user
                or invitation.status != "pending"
                or utc(invitation.code_expires_at) <= now
                or (invitation.expires_at is not None and utc(invitation.expires_at) <= now)
                or row.owner_id == user
                or self.repository.member(project_id, user) is not None
            ):
                raise unavailable
            assert row is not None
            self.writable(row, administrative=True, revocation=not accept)
            self.repository.set_invitation_status(
                invitation.id, "accepted" if accept else "declined"
            )
            result = None
            if accept:
                member = Member(
                    user_id=user,
                    roles=list(invitation.roles),
                    expires_at=invitation.expires_at,
                    role_grants=invitation.role_grants,
                )
                self.repository.deny(project_id, user, False)
                self.repository.add_member(project_id, member)
                self.repository.invalidate(project_id, user)
                result = self.access_for(row, user)
            self.repository.change_state(
                project_id,
                user,
                {},
                "access.invitation.accepted" if accept else "access.invitation.declined",
            )
        return result

    def validate_roles(self, row: Project, user: UUID, patch: MembershipPatch) -> None:
        access = self.require(row, user, "project:members:manage")
        definitions = {r.key: set(r.permissions) for r in self.roles(user, row.id).items}
        if any(role not in definitions for role in patch.roles):
            raise AccessError(422, "Invalid project input")
        if any(not definitions[role].issubset(access.permissions) for role in patch.roles):
            raise AccessError(403, "Cannot delegate unavailable privileges")
        if patch.role_grants is not None:
            if len({g.role for g in patch.role_grants}) != len(patch.role_grants) or {
                g.role for g in patch.role_grants
            } != set(patch.roles):
                raise AccessError(422, "Role grants must match roles")
            for grant in patch.role_grants:
                self.validate_expiry(grant.expires_at)

    def grants(
        self, patch: MembershipPatch, expiry: datetime | None
    ) -> builtins.list[dict[str, str | None]]:
        if patch.role_grants is not None:
            return [g.model_dump(mode="json") for g in patch.role_grants]
        return [
            {"role": role, "expires_at": utc(expiry).isoformat() if expiry else None}
            for role in patch.roles
        ]
