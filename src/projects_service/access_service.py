import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import func, select

from projects_service.access_domain import (
    OWNER,
    ROLE_NAMES,
    ROLE_PERMISSIONS,
    Access,
    AccessError,
    InvitationCreated,
    InvitationDraft,
    Member,
    MemberPage,
    MembershipPatch,
    Role,
    RolePage,
    utc,
)
from projects_service.access_repository import AccessRepository, to_member
from projects_service.domain import Project, ProjectPage, ProjectPatch
from projects_service.models import InvitationRecord, MemberRecord, ProjectRecord
from projects_service.repository import to_project


class AccessService:
    def __init__(self, repository: AccessRepository, clock: Callable[[], datetime]) -> None:
        self.repository = repository
        self.clock = clock

    def access_for(self, row: ProjectRecord, user: UUID) -> Access:
        owner = row.owner_id == user
        member = None if owner else self.repository.member(row.id, user)
        roles = (
            ["owner"]
            if owner
            else (
                sorted(member.roles)
                if member
                and (member.expires_at is None or utc(member.expires_at) > utc(self.clock()))
                else []
            )
        )
        permissions = (
            set(OWNER)
            if owner
            else set().union(*(ROLE_PERMISSIONS.get(role, frozenset()) for role in roles))
        )
        return Access(
            project_id=row.id,
            user_id=user,
            is_owner=owner,
            roles=roles,
            permissions=sorted(permissions),
        )

    def require(
        self, row: ProjectRecord | None, user: UUID, permission: str = "project:read"
    ) -> Access:
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

    def project(self, row: ProjectRecord, user: UUID) -> Project:
        access = self.require(row, user)
        return to_project(row).model_copy(update={"permissions": access.permissions})

    def get(self, user: UUID, project_id: UUID) -> Project | None:
        row = self.repository.project(project_id)
        if row is None or "project:read" not in self.access_for(row, user).permissions:
            return None
        return self.project(row, user)

    def list(self, user: UUID, *, limit: int, offset: int, q: str) -> ProjectPage:
        conditions = [self.repository.visible(user, utc(self.clock()))]
        if q:
            conditions.append(func.lower(ProjectRecord.name).contains(q.lower(), autoescape=True))
        session = self.repository.session
        total = session.scalar(select(func.count()).select_from(ProjectRecord).where(*conditions))
        rows = session.scalars(
            select(ProjectRecord)
            .where(*conditions)
            .order_by(ProjectRecord.created_at.desc(), ProjectRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return ProjectPage(
            items=[self.project(row, user) for row in rows],
            total=total or 0,
            limit=limit,
            offset=offset,
        )

    def patch_project(self, user: UUID, project_id: UUID, patch: ProjectPatch) -> Project | None:
        from sqlalchemy import update

        with self.repository.locked_project(project_id) as row:
            if row is None or "project:read" not in self.access_for(row, user).permissions:
                return None
            self.require(row, user, "project:update")
            # Owner predicate remains for existing owner SQL contract; members are
            # authorized under the same project lock held until commit.
            statement = update(ProjectRecord).where(ProjectRecord.id == project_id)
            if row.owner_id == user:
                statement = statement.where(ProjectRecord.owner_id == user)
            changed = self.repository.session.scalar(
                statement.values(**patch.model_dump(exclude_unset=True))
                .returning(ProjectRecord)
                .execution_options(populate_existing=True)
            )
            assert changed is not None
            result = self.project(changed, user)
        return result

    def delete_project(self, user: UUID, project_id: UUID) -> bool:
        from sqlalchemy import delete

        with self.repository.locked_project(project_id) as row:
            if row is None or "project:read" not in self.access_for(row, user).permissions:
                return False
            self.require(row, user, "project:delete")
            self.repository.session.execute(
                delete(ProjectRecord).where(
                    ProjectRecord.id == project_id, ProjectRecord.owner_id == user
                )
            )
        return True

    def roles(self, user: UUID, project_id: UUID) -> RolePage:
        self.require(self.repository.project(project_id), user, "project:members:read")
        return RolePage(
            items=[
                Role(key=key, name=ROLE_NAMES[key], permissions=sorted(value))
                for key, value in ROLE_PERMISSIONS.items()
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
        items = ([owner] if offset == 0 else []) + [to_member(member) for member in records]
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
            if member is None:
                raise AccessError(404, "Member unavailable")
            self.repository.invalidate(project_id, target)
            if patch is None:
                self.repository.session.delete(member)
                result = None
            else:
                if "expires_at" in patch.model_fields_set:
                    self.validate_expiry(patch.expires_at)
                    member.expires_at = utc(patch.expires_at) if patch.expires_at else None
                member.roles = list(patch.roles)
                result = to_member(member)
        return result

    def invite(self, user: UUID, project_id: UUID, draft: InvitationDraft) -> InvitationCreated:
        with self.repository.locked_project(project_id) as row:
            self.require(row, user, "project:members:manage")
            assert row is not None
            if draft.user_id == row.owner_id or self.repository.member(project_id, draft.user_id):
                raise AccessError(409, "Member already exists")
            self.validate_expiry(draft.expires_at)
            code = secrets.token_urlsafe(32)
            expiry = utc(draft.expires_at) if draft.expires_at else None
            code_expiry = utc(self.clock()) + timedelta(days=7)
            invitation = InvitationRecord(
                id=uuid4(),
                project_id=project_id,
                user_id=draft.user_id,
                roles=list(draft.roles),
                expires_at=expiry,
                code_expires_at=code_expiry,
                code_hash=sha256(code.encode()).hexdigest(),
                status="pending",
            )
            self.repository.session.add(invitation)
            result = InvitationCreated(
                id=invitation.id,
                project_id=project_id,
                user_id=draft.user_id,
                roles=list(draft.roles),
                expires_at=expiry,
                code=code,
                code_expires_at=code_expiry,
            )
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
            invitation.status = "accepted" if accept else "declined"
            result = None
            if accept:
                member = MemberRecord(
                    project_id=project_id,
                    user_id=user,
                    roles=list(invitation.roles),
                    expires_at=invitation.expires_at,
                )
                self.repository.session.add(member)
                self.repository.session.flush()
                self.repository.invalidate(project_id, user)
                result = self.access_for(row, user)
        return result
