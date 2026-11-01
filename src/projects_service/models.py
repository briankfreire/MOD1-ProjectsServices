from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProjectRecord(Base):
    __tablename__ = "projects"
    __table_args__ = {"schema": "projects"}

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="planned", server_default="active"
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    deletion_frozen: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


Index(
    "ix_projects_owner_created_id",
    ProjectRecord.owner_id,
    ProjectRecord.created_at.desc(),
    ProjectRecord.id.desc(),
)


class MemberRecord(Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"), {"schema": "projects"})

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    role_grants: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )


Index("ix_members_user_project", MemberRecord.user_id, MemberRecord.project_id)


class InvitationRecord(Base):
    __tablename__ = "invitations"
    __table_args__ = {"schema": "projects"}

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    role_grants: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    code_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)


Index("ix_invitations_project_user", InvitationRecord.project_id, InvitationRecord.user_id)


class EventRecord(Base):
    __tablename__ = "events"
    __table_args__ = {"schema": "projects"}
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class RoleRecord(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "projects"}
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.projects.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class TeamRecord(Base):
    __tablename__ = "teams"
    __table_args__ = {"schema": "projects"}
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cost_center: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class TeamMemberRecord(Base):
    __tablename__ = "team_members"
    __table_args__ = {"schema": "projects"}
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    is_manager: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weekly_hours: Mapped[str | None] = mapped_column(String(20))
    hourly_rate: Mapped[str | None] = mapped_column(String(30))
    currency: Mapped[str | None] = mapped_column(String(3))


class TeamInvitationRecord(Base):
    __tablename__ = "team_invitations"
    __table_args__ = {"schema": "projects"}
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.teams.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    is_manager: Mapped[bool] = mapped_column(Boolean, nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    code_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)


class TeamLinkRecord(Base):
    __tablename__ = "team_links"
    __table_args__ = {"schema": "projects"}
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.projects.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.teams.id", ondelete="CASCADE"), primary_key=True
    )
    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DenyRecord(Base):
    __tablename__ = "project_denies"
    __table_args__ = {"schema": "projects"}
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)


class AllocationRecord(Base):
    __tablename__ = "allocations"
    __table_args__ = {"schema": "projects"}
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    weekly_hours: Mapped[str] = mapped_column(String(20), nullable=False)
    hourly_rate: Mapped[str | None] = mapped_column(String(30))
    currency: Mapped[str | None] = mapped_column(String(3))


class LeaseRecord(Base):
    __tablename__ = "write_leases"
    __table_args__ = (UniqueConstraint("project_id", "operation_id"), {"schema": "projects"})
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    operation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    released: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecommendationRecord(Base):
    __tablename__ = "recommendations"
    __table_args__ = {"schema": "projects"}
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class OutboxRecord(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = {"schema": "projects"}
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.recommendations.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")


class NotificationRecord(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("recommendation_id", "recipient_id"),
        {"schema": "projects"},
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False
    )
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.recommendations.id", ondelete="CASCADE"), nullable=False
    )
    recipient_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index(
    "ix_notifications_recipient_created_id",
    NotificationRecord.recipient_id,
    NotificationRecord.created_at.desc(),
    NotificationRecord.id.desc(),
)


class AccessObservationRecord(Base):
    """Operational observations deliberately have no FK to the locked project row."""

    __tablename__ = "access_observations"
    __table_args__ = {"schema": "projects"}
    project_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    observed_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_signature: Mapped[str] = mapped_column(String(64), nullable=False)
