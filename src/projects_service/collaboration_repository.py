"""SQL persistence for collaboration; transactions are owned by resource locks."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from projects_service.access_domain import OWNER, ROLE_PERMISSIONS, utc
from projects_service.access_repository import AccessRepository
from projects_service.domain import Project
from projects_service.models import (
    AccessObservationRecord,
    AllocationRecord,
    DenyRecord,
    EventRecord,
    InvitationRecord,
    LeaseRecord,
    MemberRecord,
    NotificationRecord,
    OutboxRecord,
    ProjectRecord,
    RecommendationRecord,
    RoleRecord,
    TeamInvitationRecord,
    TeamLinkRecord,
    TeamMemberRecord,
    TeamRecord,
)


def snapshot(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class CollaborationRepository(AccessRepository):
    def __init__(
        self, session: Session, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        super().__init__(session)
        self.clock = clock

    def access_signature(self, project: Project, user: UUID) -> str:
        if project.owner_id == user:
            roles = ["owner"]
            permissions = sorted(OWNER)
            sources = [{"type": "owner"}]
        else:
            sources = self.sources(project.id, user, self.clock())
            roles = sorted({role for source in sources for role in source["roles"]})
            definitions = {
                **ROLE_PERMISSIONS,
                **{r["key"]: frozenset(r["permissions"]) for r in self.definitions(project.id)},
            }
            permissions = sorted(
                set().union(*(definitions.get(role, frozenset()) for role in roles))
            )
        return sha256(
            json.dumps(
                {"roles": roles, "permissions": permissions, "sources": sources},
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()

    def observe_activity(self, project: Project, user: UUID, now: datetime) -> None:
        now = utc(now)
        signature = self.access_signature(project, user)
        insert = (
            pg_insert if self.session.get_bind().dialect.name == "postgresql" else sqlite_insert
        )
        record = AccessObservationRecord
        statement = insert(record).values(
            project_id=project.id,
            user_id=user,
            observed_since=now,
            last_activity_at=now,
            access_signature=signature,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[record.project_id, record.user_id],
            set_={
                "observed_since": case(
                    (record.access_signature != signature, now), else_=record.observed_since
                ),
                "last_activity_at": case(
                    (or_(record.last_activity_at.is_(None), record.last_activity_at < now), now),
                    else_=record.last_activity_at,
                ),
                "access_signature": signature,
            },
            where=or_(
                record.access_signature != signature,
                record.last_activity_at.is_(None),
                record.last_activity_at < now - timedelta(seconds=60),
            ),
        )
        self.session.execute(statement)
        self.session.commit()

    def observations(self, project_id: UUID) -> dict[UUID, dict[str, Any]]:
        return {
            row.user_id: snapshot(row)
            for row in self.session.scalars(
                select(AccessObservationRecord).where(
                    AccessObservationRecord.project_id == project_id
                )
            )
        }

    def end_read(self) -> None:
        self.session.rollback()

    def lock_observations(self, project_id: UUID) -> None:
        # Same order as reset_access_observations; concurrent authorized activity
        # commits before this snapshot or waits until the human decision commits.
        self.session.scalars(
            select(AccessObservationRecord)
            .where(AccessObservationRecord.project_id == project_id)
            .order_by(AccessObservationRecord.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()

    def lease_generation(self, project_id: UUID) -> int:
        # Leases are durable receipts, including released writes. A completed
        # intervening Backlog write must invalidate an earlier external snapshot.
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(LeaseRecord)
                .where(LeaseRecord.project_id == project_id)
            )
            or 0
        )

    def reset_access_observations(self, project_id: UUID) -> None:
        project = self.project(project_id)
        if project is None:
            return
        now = utc(self.clock())
        users = {project.owner_id}
        users.update(
            self.session.scalars(
                select(MemberRecord.user_id).where(MemberRecord.project_id == project_id)
            )
        )
        users.update(
            self.session.scalars(
                select(TeamMemberRecord.user_id)
                .join(TeamLinkRecord, TeamMemberRecord.team_id == TeamLinkRecord.team_id)
                .where(TeamLinkRecord.project_id == project_id)
            )
        )
        previous = self.observations(project_id)
        for user in sorted(users | set(previous)):
            row = self.session.get(AccessObservationRecord, (project_id, user))
            signature = self.access_signature(project, user)
            if row is None:
                row = AccessObservationRecord(
                    project_id=project_id,
                    user_id=user,
                    observed_since=now,
                    last_activity_at=None,
                    access_signature=signature,
                )
                self.session.add(row)
            else:
                row.observed_since = now
                row.last_activity_at = None
                row.access_signature = signature
        self.session.flush()

    def change_state(
        self, project_id: UUID, actor: UUID, changes: dict[str, object], action: str
    ) -> Project:
        result = super().change_state(project_id, actor, changes, action)
        if action.startswith("access.") or action == "project.transferred":
            self.reset_access_observations(project_id)
        return result

    def delete_project(self, project_id: UUID, owner: UUID) -> None:
        self.session.execute(
            delete(AccessObservationRecord).where(AccessObservationRecord.project_id == project_id)
        )
        super().delete_project(project_id, owner)

    def definitions(self, project_id: UUID) -> list[dict[str, Any]]:
        return [
            snapshot(r)
            for r in self.session.scalars(
                select(RoleRecord)
                .where(RoleRecord.project_id == project_id)
                .order_by(RoleRecord.key)
            )
        ]

    def sources(self, project_id: UUID, user: UUID, now: datetime) -> list[dict[str, Any]]:
        if self.session.get(DenyRecord, (project_id, user)):
            return []
        sources: list[dict[str, Any]] = []
        member = self.member(project_id, user)
        if member:
            roles = (
                [
                    g["role"]
                    for g in member.role_grants
                    if g.get("expires_at") is None
                    or datetime.fromisoformat(str(g["expires_at"])) > utc(now)
                ]
                if member.role_grants
                else member.roles
                if member.expires_at is None or utc(member.expires_at) > utc(now)
                else []
            )
            if roles:
                sources.append({"type": "direct", "roles": roles})
        rows = self.session.scalars(
            select(TeamLinkRecord)
            .join(TeamMemberRecord, TeamLinkRecord.team_id == TeamMemberRecord.team_id)
            .where(TeamLinkRecord.project_id == project_id, TeamMemberRecord.user_id == user)
        )
        for link in rows:
            if link.expires_at is None or utc(link.expires_at) > utc(now):
                sources.append(
                    {"type": "team", "team_id": str(link.team_id), "roles": list(link.roles)}
                )
        return sources

    def role_save(self, project_id: UUID, key: str, data: dict[str, Any]) -> dict[str, Any]:
        row = self.session.get(RoleRecord, (project_id, key))
        if row is None:
            row = RoleRecord(project_id=project_id, key=key, **data)
            self.session.add(row)
        else:
            for name, value in data.items():
                setattr(row, name, value)
        self.session.flush()
        return snapshot(row)

    def role_linked(self, project_id: UUID, key: str) -> bool:
        for model in (MemberRecord, InvitationRecord, TeamLinkRecord):
            for row in self.session.scalars(select(model).where(model.project_id == project_id)):
                if key in getattr(row, "roles"):
                    return True
        return False

    def role_delete(self, project_id: UUID, key: str) -> None:
        self.session.execute(
            delete(RoleRecord).where(RoleRecord.project_id == project_id, RoleRecord.key == key)
        )

    def deny(self, project_id: UUID, user: UUID, denied: bool) -> None:
        record = self.session.get(DenyRecord, (project_id, user))
        if denied and record is None:
            self.session.add(DenyRecord(project_id=project_id, user_id=user))
        elif not denied and record:
            self.session.delete(record)
        self.session.flush()

    def team(self, team_id: UUID) -> dict[str, Any] | None:
        row = self.session.get(TeamRecord, team_id, populate_existing=True)
        return snapshot(row) if row else None

    @contextmanager
    def locked_team(self, team_id: UUID) -> Iterator[dict[str, Any] | None]:
        if self.session.in_transaction():
            self.session.rollback()
        with self.session.begin():
            if self.session.get_bind().dialect.name == "sqlite":
                self.session.execute(text("BEGIN IMMEDIATE"))
            row = self.session.scalar(
                select(TeamRecord)
                .where(TeamRecord.id == team_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            yield snapshot(row) if row else None

    def teams(self, user: UUID) -> list[dict[str, Any]]:
        membership = select(TeamMemberRecord.team_id).where(TeamMemberRecord.user_id == user)
        return [
            snapshot(r)
            for r in self.session.scalars(
                select(TeamRecord)
                .where(TeamRecord.id.in_(membership))
                .order_by(TeamRecord.created_at.desc(), TeamRecord.id)
            )
        ]

    def team_members(self, team_id: UUID) -> list[dict[str, Any]]:
        return [
            snapshot(r)
            for r in self.session.scalars(
                select(TeamMemberRecord)
                .where(TeamMemberRecord.team_id == team_id)
                .order_by(TeamMemberRecord.user_id)
            )
        ]

    def team_save(self, team_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
        record = self.session.get(TeamRecord, team_id)
        if record is None:
            record = TeamRecord(id=team_id, **data)
            self.session.add(record)
        else:
            for key, value in data.items():
                setattr(record, key, value)
            record.version += 1
        self.session.flush()
        for link in sorted(
            self.session.scalars(select(TeamLinkRecord).where(TeamLinkRecord.team_id == team_id)),
            key=lambda row: row.project_id,
        ):
            self.reset_access_observations(link.project_id)
        return snapshot(record)

    def team_member_save(
        self, team_id: UUID, user: UUID, data: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        record = self.session.get(TeamMemberRecord, (team_id, user))
        if data is None:
            if record:
                self.session.delete(record)
            self.session.flush()
            return None
        if record is None:
            record = TeamMemberRecord(team_id=team_id, user_id=user, **data)
            self.session.add(record)
        else:
            for key, value in data.items():
                setattr(record, key, value)
        self.session.flush()
        return snapshot(record)

    def commit(self) -> None:
        self.session.commit()

    def team_invitation(self, code_hash: str) -> dict[str, Any] | None:
        row = self.session.scalar(
            select(TeamInvitationRecord)
            .where(TeamInvitationRecord.code_hash == code_hash)
            .execution_options(populate_existing=True)
        )
        return snapshot(row) if row else None

    def team_invitation_save(self, data: dict[str, Any]) -> None:
        self.session.add(TeamInvitationRecord(**data))
        self.session.flush()

    def consume_team_invitation(self, invitation_id: UUID, status: str) -> None:
        row = self.session.get(TeamInvitationRecord, invitation_id)
        assert row is not None
        row.status = status
        self.session.flush()

    def project_teams(self, project_id: UUID) -> list[dict[str, Any]]:
        return [
            snapshot(r)
            for r in self.session.scalars(
                select(TeamLinkRecord)
                .where(TeamLinkRecord.project_id == project_id)
                .order_by(TeamLinkRecord.team_id)
            )
        ]

    def link_team(
        self, project_id: UUID, team_id: UUID, data: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        row = self.session.get(TeamLinkRecord, (project_id, team_id))
        if data is None:
            if row:
                self.session.delete(row)
            self.session.flush()
            return None
        if row is None:
            row = TeamLinkRecord(project_id=project_id, team_id=team_id, **data)
            self.session.add(row)
        else:
            for key, value in data.items():
                setattr(row, key, value)
        self.session.flush()
        return snapshot(row)

    def allocations(
        self, *, project_id: UUID | None = None, user: UUID | None = None
    ) -> list[dict[str, Any]]:
        query = select(AllocationRecord)
        if project_id:
            query = query.where(AllocationRecord.project_id == project_id)
        if user:
            query = query.where(AllocationRecord.user_id == user)
        return [
            snapshot(r)
            for r in self.session.scalars(
                query.order_by(AllocationRecord.project_id, AllocationRecord.user_id)
            )
        ]

    def allocation_save(self, project_id: UUID, user: UUID, data: dict[str, Any]) -> dict[str, Any]:
        row = self.session.get(AllocationRecord, (project_id, user))
        if row is None:
            row = AllocationRecord(project_id=project_id, user_id=user, **data)
            self.session.add(row)
        else:
            for key, value in data.items():
                setattr(row, key, value)
        self.session.flush()
        return snapshot(row)

    def lease(self, project_id: UUID, operation: UUID) -> dict[str, Any] | None:
        row = self.session.scalar(
            select(LeaseRecord).where(
                LeaseRecord.project_id == project_id, LeaseRecord.operation_id == operation
            )
        )
        return snapshot(row) if row else None

    def lease_add(self, project_id: UUID, actor: UUID, operation: UUID) -> UUID:
        lease_id = uuid4()
        self.session.add(
            LeaseRecord(
                id=lease_id,
                project_id=project_id,
                actor_id=actor,
                operation_id=operation,
                released=False,
                created_at=datetime.now(UTC),
            )
        )
        self.session.flush()
        return lease_id

    def lease_release(self, project_id: UUID, actor: UUID, lease_id: UUID) -> bool:
        row = self.session.get(LeaseRecord, lease_id)
        if row is None or row.project_id != project_id or row.actor_id != actor:
            return False
        row.released = True
        self.session.flush()
        return True

    def active_leases(self, project_id: UUID) -> bool:
        return bool(
            self.session.scalar(
                select(LeaseRecord.id)
                .where(LeaseRecord.project_id == project_id, LeaseRecord.released.is_(False))
                .limit(1)
            )
        )

    def freeze(self, project_id: UUID, frozen: bool) -> None:
        row = self.session.get(ProjectRecord, project_id)
        assert row is not None
        row.deletion_frozen = frozen
        self.session.flush()

    def relevant(self, project_id: UUID) -> bool:
        for model in (
            MemberRecord,
            InvitationRecord,
            TeamLinkRecord,
            AllocationRecord,
            RecommendationRecord,
            RoleRecord,
            DenyRecord,
        ):
            if self.session.scalar(
                select(func.count()).select_from(model).where(model.project_id == project_id)
            ):
                return True
        return bool(
            self.session.scalar(
                select(func.count())
                .select_from(EventRecord)
                .where(
                    EventRecord.project_id == project_id, EventRecord.action != "project.created"
                )
            )
        )

    def recommendation_save(self, data: dict[str, Any]) -> None:
        row = self.session.get(RecommendationRecord, UUID(data["id"]))
        if row is None:
            self.session.add(
                RecommendationRecord(
                    id=UUID(data["id"]), project_id=UUID(data["project_id"]), payload=data
                )
            )
        else:
            row.payload = data
        self.session.flush()

    def recommendations(self, project_id: UUID) -> list[dict[str, Any]]:
        return [
            r.payload
            for r in self.session.scalars(
                select(RecommendationRecord).where(RecommendationRecord.project_id == project_id)
            )
        ]

    def outbox(
        self,
        recommendation: dict[str, Any],
        *,
        recipients: set[UUID] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        existing = self.session.scalar(
            select(OutboxRecord).where(OutboxRecord.recommendation_id == UUID(recommendation["id"]))
        )
        if existing is None:
            existing = OutboxRecord(
                id=uuid4(),
                recommendation_id=UUID(recommendation["id"]),
                payload={
                    "kind": recommendation["kind"],
                    "project_id": recommendation["project_id"],
                },
                status="pending",
            )
            self.session.add(existing)
            self.session.flush()
        if recipients is not None:
            assert created_at is not None
            for recipient in sorted(recipients):
                present = self.session.scalar(
                    select(NotificationRecord.id).where(
                        NotificationRecord.recommendation_id == UUID(recommendation["id"]),
                        NotificationRecord.recipient_id == recipient,
                    )
                )
                if present is None:
                    self.session.add(
                        NotificationRecord(
                            id=uuid4(),
                            project_id=UUID(recommendation["project_id"]),
                            recommendation_id=UUID(recommendation["id"]),
                            recipient_id=recipient,
                            kind="team_recommendation_approved",
                            title="Equipe vinculada ao projeto",
                            message=(
                                "Uma recomenda\u00e7\u00e3o de equipe foi aprovada. "
                                "Consulte seus projetos para conferir o acesso dispon\u00edvel."
                            ),
                            created_at=utc(created_at),
                            read_at=None,
                        )
                    )
            self.session.flush()
            existing.payload = {
                **existing.payload,
                "recipient_ids": [str(recipient) for recipient in sorted(recipients)],
            }
            existing.status = "delivered_in_app"
        self.session.flush()

    def notifications(self, recipient: UUID, limit: int, offset: int) -> dict[str, Any]:
        condition = NotificationRecord.recipient_id == recipient
        rows = self.session.scalars(
            select(NotificationRecord)
            .where(condition)
            .order_by(NotificationRecord.created_at.desc(), NotificationRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = (
            self.session.scalar(
                select(func.count()).select_from(NotificationRecord).where(condition)
            )
            or 0
        )
        return {
            "items": [self.notification_snapshot(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def notification_snapshot(self, row: NotificationRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "kind": row.kind,
            "title": row.title,
            "message": row.message,
            "created_at": utc(row.created_at),
            "read_at": utc(row.read_at) if row.read_at else None,
        }

    def read_notification(
        self, recipient: UUID, notification_id: UUID, now: datetime
    ) -> dict[str, Any] | None:
        condition = (
            NotificationRecord.id == notification_id,
            NotificationRecord.recipient_id == recipient,
        )
        row = self.session.scalar(
            update(NotificationRecord)
            .where(*condition, NotificationRecord.read_at.is_(None))
            .values(read_at=utc(now))
            .returning(NotificationRecord)
            .execution_options(populate_existing=True)
        )
        if row is None:
            row = self.session.scalar(select(NotificationRecord).where(*condition))
        result = self.notification_snapshot(row) if row is not None else None
        self.session.commit()
        return result

    def lock_capacity(self, user: UUID) -> None:
        if self.session.get_bind().dialect.name == "postgresql":
            key = int.from_bytes(user.bytes[:8], byteorder="big", signed=True)
            self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
