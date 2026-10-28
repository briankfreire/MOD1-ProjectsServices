from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from projects_service.domain import Project, ProjectDraft, ProjectPage, ProjectPatch
from projects_service.repository import ProjectRepository


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProjectsService:
    def __init__(
        self,
        repository: ProjectRepository,
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.repository = repository
        self.clock = clock
        self.id_factory = id_factory

    def create(self, owner_id: UUID, draft: ProjectDraft) -> Project:
        return self.repository.add(
            Project(
                id=self.id_factory(),
                owner_id=owner_id,
                name=draft.name,
                description=draft.description,
                objective=draft.objective,
                created_at=self.clock(),
            )
        )

    def list(self, owner_id: UUID, *, limit: int = 20, offset: int = 0, q: str = "") -> ProjectPage:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        q = q.strip()
        if len(q) > 120:
            raise ValueError("Invalid search")
        return self.repository.list_owned(owner_id, limit=limit, offset=offset, q=q)

    def get(self, owner_id: UUID, project_id: UUID) -> Project | None:
        return self.repository.get_owned(owner_id, project_id)

    def delete(self, owner_id: UUID, project_id: UUID) -> bool:
        return self.repository.delete_owned(owner_id, project_id)

    def patch(self, owner_id: UUID, project_id: UUID, patch: ProjectPatch) -> Project | None:
        return self.repository.patch_owned(owner_id, project_id, patch)
