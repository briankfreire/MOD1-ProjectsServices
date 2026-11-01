import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from projects_service.access_domain import AccessError, Invitation, Member, utc
from projects_service.domain import Metadata, Project, ProjectPage, ProjectPatch
from projects_service.models import EventRecord, InvitationRecord, MemberRecord, ProjectRecord
from projects_service.repository import to_project


def to_member(row: MemberRecord) -> Member:
    return Member(
        user_id=row.user_id,
        roles=sorted(row.roles),
        expires_at=utc(row.expires_at) if row.expires_at else None,
        role_grants=list(row.role_grants),
    )


class AccessRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @contextmanager
    def locked_project(self, project_id: UUID) -> Iterator[Project | None]:
        # Requests own their Session. End any read snapshot before obtaining the lock,
        # so authorization always sees the latest committed membership after waiting.
        if self.session.in_transaction():
            self.session.rollback()
        with self.session.begin():
            if self.session.get_bind().dialect.name == "sqlite":
                self.session.execute(text("BEGIN IMMEDIATE"))
            row = self.session.scalar(
                select(ProjectRecord)
                .where(ProjectRecord.id == project_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            yield to_project(row) if row is not None else None

    def project(self, project_id: UUID) -> Project | None:
        row = self.session.get(ProjectRecord, project_id)
        return to_project(row) if row is not None else None

    def member(self, project_id: UUID, user_id: UUID) -> Member | None:
        row = self.session.get(MemberRecord, (project_id, user_id), populate_existing=True)
        return to_member(row) if row is not None else None

    def members(self, project_id: UUID, *, limit: int, offset: int) -> list[Member]:
        return list(
            to_member(row)
            for row in self.session.scalars(
                select(MemberRecord)
                .where(MemberRecord.project_id == project_id)
                .order_by(MemberRecord.user_id)
                .limit(limit)
                .offset(offset)
            )
        )

    def member_count(self, project_id: UUID) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(MemberRecord)
                .where(MemberRecord.project_id == project_id)
            )
            or 0
        )

    def visible(self, user_id: UUID, now: datetime) -> ColumnElement[bool]:
        active = (
            select(MemberRecord.project_id)
            .where(
                MemberRecord.project_id == ProjectRecord.id,
                MemberRecord.user_id == user_id,
                func.json_array_length(MemberRecord.roles) > 0,
                or_(MemberRecord.expires_at.is_(None), MemberRecord.expires_at > now),
            )
            .exists()
        )
        return or_(ProjectRecord.owner_id == user_id, active)

    def invalidate(self, project_id: UUID, user_id: UUID) -> None:
        self.session.execute(
            update(InvitationRecord)
            .where(
                InvitationRecord.project_id == project_id,
                InvitationRecord.user_id == user_id,
                InvitationRecord.status == "pending",
            )
            .values(status="invalidated")
        )

    def invitation(self, code_hash: str) -> Invitation | None:
        row = self.session.scalar(
            select(InvitationRecord)
            .where(InvitationRecord.code_hash == code_hash)
            .execution_options(populate_existing=True)
        )
        if row is None:
            return None
        return Invitation(
            id=row.id,
            project_id=row.project_id,
            user_id=row.user_id,
            roles=list(row.roles),
            role_grants=list(row.role_grants),
            expires_at=utc(row.expires_at) if row.expires_at else None,
            code_expires_at=utc(row.code_expires_at),
            status=row.status,
        )

    def list_visible(
        self, user: UUID, now: datetime, *, limit: int, offset: int, q: str
    ) -> ProjectPage:
        conditions = [self.visible(user, now)]
        if q:
            conditions.append(func.lower(ProjectRecord.name).contains(q.lower(), autoescape=True))
        total = self.session.scalar(
            select(func.count()).select_from(ProjectRecord).where(*conditions)
        )
        rows = self.session.scalars(
            select(ProjectRecord)
            .where(*conditions)
            .order_by(ProjectRecord.created_at.desc(), ProjectRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return ProjectPage(
            items=[to_project(row) for row in rows], total=total or 0, limit=limit, offset=offset
        )

    # Mutations run inside locked_project: it owns commit/rollback and serialization.
    # Authorization and lifecycle rules remain in AccessService.
    def patch_project(
        self, project_id: UUID, user: UUID, patch: ProjectPatch, *, owner: bool
    ) -> Project:
        current = self.session.get(ProjectRecord, project_id)
        assert current is not None
        values = patch.model_dump(mode="json", exclude_unset=True)
        metadata = {key: values.pop(key) for key in list(values) if key in Metadata.model_fields}
        details = {**current.details, **metadata}
        try:
            Metadata.model_validate(details)
        except ValidationError:
            raise AccessError(422, "Invalid project input") from None
        statement = update(ProjectRecord).where(ProjectRecord.id == project_id)
        if owner:
            statement = statement.where(ProjectRecord.owner_id == user)
        row = self.session.scalar(
            statement.values(**values, details=details, version=current.version + 1)
            .returning(ProjectRecord)
            .execution_options(populate_existing=True)
        )
        assert row is not None
        self.event(
            project_id,
            user,
            "project.updated",
            row.version,
            patch.model_dump(mode="json", exclude_unset=True),
        )
        return to_project(row)

    def delete_project(self, project_id: UUID, owner: UUID) -> None:
        self.session.execute(
            delete(ProjectRecord).where(
                ProjectRecord.id == project_id, ProjectRecord.owner_id == owner
            )
        )

    def delete_member(self, project_id: UUID, user: UUID) -> None:
        self.session.execute(
            delete(MemberRecord).where(
                MemberRecord.project_id == project_id, MemberRecord.user_id == user
            )
        )

    def update_member(self, project_id: UUID, member: Member) -> None:
        self.session.execute(
            update(MemberRecord)
            .where(MemberRecord.project_id == project_id, MemberRecord.user_id == member.user_id)
            .values(
                roles=list(member.roles),
                expires_at=member.expires_at,
                role_grants=member.role_grants,
            )
        )

    def add_invitation(self, invitation: Invitation, code_hash: str) -> None:
        self.session.add(InvitationRecord(**invitation.model_dump(), code_hash=code_hash))

    def set_invitation_status(self, invitation_id: UUID, status: str) -> None:
        self.session.execute(
            update(InvitationRecord)
            .where(InvitationRecord.id == invitation_id)
            .values(status=status)
        )

    def add_member(self, project_id: UUID, member: Member) -> None:
        self.session.add(
            MemberRecord(
                project_id=project_id,
                user_id=member.user_id,
                roles=list(member.roles),
                expires_at=member.expires_at,
                role_grants=member.role_grants,
            )
        )
        self.session.flush()

    def event(
        self, project_id: UUID, actor: UUID, action: str, version: int, changes: dict[str, object]
    ) -> None:
        self.session.add(
            EventRecord(
                id=uuid4(),
                project_id=project_id,
                actor_id=actor,
                action=action,
                version=version,
                changes=json.loads(json.dumps(changes, default=str)),
                created_at=datetime.now(UTC),
            )
        )
        self.session.flush()

    def creation_event(self, project: Project, actor: UUID) -> None:
        self.event(project.id, actor, "project.created", 1, {})
        self.session.commit()

    def change_state(
        self, project_id: UUID, actor: UUID, changes: dict[str, object], action: str
    ) -> Project:
        record = self.session.get(ProjectRecord, project_id)
        assert record is not None
        for key, value in changes.items():
            setattr(record, key, value)
        record.version += 1
        self.event(project_id, actor, action, record.version, changes)
        self.session.flush()
        return to_project(record)

    def events(
        self, project_id: UUID, limit: int, offset: int, action: str = ""
    ) -> dict[str, object]:
        conditions = [EventRecord.project_id == project_id]
        if action:
            conditions.append(EventRecord.action.contains(action, autoescape=True))
        rows = list(
            self.session.scalars(
                select(EventRecord)
                .where(*conditions)
                .order_by(EventRecord.created_at.desc(), EventRecord.id)
                .limit(limit)
                .offset(offset)
            )
        )
        total = (
            self.session.scalar(select(func.count()).select_from(EventRecord).where(*conditions))
            or 0
        )
        return {
            "items": [
                {
                    "id": r.id,
                    "actor_id": r.actor_id,
                    "action": r.action,
                    "created_at": utc(r.created_at),
                    "version": r.version,
                    "changes": r.changes,
                    "origin": "api",
                    "result": "success",
                }
                for r in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def frozen(self, project_id: UUID) -> bool:
        return bool(
            self.session.scalar(
                select(ProjectRecord.deletion_frozen).where(ProjectRecord.id == project_id)
            )
        )

    def all_projects(self, q: str = "") -> list[Project]:
        statement = select(ProjectRecord)
        if q:
            statement = statement.where(
                func.lower(ProjectRecord.name).contains(q.lower(), autoescape=True)
            )
        return [
            to_project(r)
            for r in self.session.scalars(
                statement.order_by(ProjectRecord.created_at.desc(), ProjectRecord.id.desc())
            )
        ]
