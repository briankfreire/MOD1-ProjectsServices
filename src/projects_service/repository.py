from datetime import UTC
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from projects_service.domain import Project, ProjectPage, ProjectPatch
from projects_service.models import ProjectRecord


def to_project(record: ProjectRecord) -> Project:
    created = record.created_at
    created = created.replace(tzinfo=UTC) if created.tzinfo is None else created.astimezone(UTC)
    return Project(
        id=record.id,
        owner_id=record.owner_id,
        name=record.name,
        description=record.description,
        objective=record.objective,
        created_at=created,
    )


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, project: Project) -> Project:
        record = ProjectRecord(**project.model_dump())
        try:
            self.session.add(record)
            self.session.commit()
            return to_project(record)
        except Exception:
            self.session.rollback()
            raise

    def list_owned(self, owner_id: UUID, *, limit: int, offset: int, q: str = "") -> ProjectPage:
        own = ProjectRecord.owner_id == owner_id
        conditions = [own]
        if q:
            conditions.append(func.lower(ProjectRecord.name).contains(q.lower(), autoescape=True))
        total = self.session.scalar(
            select(func.count()).select_from(ProjectRecord).where(*conditions)
        )
        records = self.session.scalars(
            select(ProjectRecord)
            .where(*conditions)
            .order_by(ProjectRecord.created_at.desc(), ProjectRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return ProjectPage(
            items=[to_project(row) for row in records], total=total or 0, limit=limit, offset=offset
        )

    def get_owned(self, owner_id: UUID, project_id: UUID) -> Project | None:
        row = self.session.scalar(
            select(ProjectRecord).where(
                ProjectRecord.id == project_id, ProjectRecord.owner_id == owner_id
            )
        )
        return to_project(row) if row else None

    def patch_owned(self, owner_id: UUID, project_id: UUID, patch: ProjectPatch) -> Project | None:
        try:
            row = self.session.scalar(
                update(ProjectRecord)
                .where(ProjectRecord.id == project_id, ProjectRecord.owner_id == owner_id)
                .values(**patch.model_dump(exclude_unset=True))
                .returning(ProjectRecord)
            )
            project = to_project(row) if row else None
            self.session.commit()
            return project
        except Exception:
            self.session.rollback()
            raise

    def delete_owned(self, owner_id: UUID, project_id: UUID) -> bool:
        try:
            deleted_id = self.session.scalar(
                delete(ProjectRecord)
                .where(ProjectRecord.id == project_id, ProjectRecord.owner_id == owner_id)
                .returning(ProjectRecord.id)
            )
            self.session.commit()
            return deleted_id is not None
        except Exception:
            self.session.rollback()
            raise
