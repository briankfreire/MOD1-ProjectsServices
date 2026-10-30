from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
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
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    code_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)


Index("ix_invitations_project_user", InvitationRecord.project_id, InvitationRecord.user_id)
