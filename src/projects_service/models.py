from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String, Text, Uuid
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index(
    "ix_projects_owner_created_id",
    ProjectRecord.owner_id,
    ProjectRecord.created_at.desc(),
    ProjectRecord.id.desc(),
)
