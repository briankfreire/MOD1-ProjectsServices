from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from projects_service.access_domain import Member, utc
from projects_service.models import InvitationRecord, MemberRecord, ProjectRecord


def to_member(row: MemberRecord) -> Member:
    return Member(
        user_id=row.user_id,
        roles=sorted(row.roles),
        expires_at=utc(row.expires_at) if row.expires_at else None,
    )


class AccessRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @contextmanager
    def locked_project(self, project_id: UUID) -> Iterator[ProjectRecord | None]:
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
            yield row

    def project(self, project_id: UUID) -> ProjectRecord | None:
        return self.session.get(ProjectRecord, project_id)

    def member(self, project_id: UUID, user_id: UUID) -> MemberRecord | None:
        return self.session.get(MemberRecord, (project_id, user_id), populate_existing=True)

    def members(self, project_id: UUID, *, limit: int, offset: int) -> list[MemberRecord]:
        return list(
            self.session.scalars(
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

    def invitation(self, code_hash: str) -> InvitationRecord | None:
        return self.session.scalar(
            select(InvitationRecord)
            .where(InvitationRecord.code_hash == code_hash)
            .execution_options(populate_existing=True)
        )
