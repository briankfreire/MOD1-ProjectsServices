from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from projects_service.access_domain import OWNER
from projects_service.access_service import AccessService
from projects_service.collaboration_service import CollaborationService
from projects_service.domain import Project, ProjectDraft, ProjectPage, ProjectPatch
from projects_service.recommendation_service import RecommendationService
from projects_service.repository import ProjectRepository


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProjectsService:
    def __init__(
        self,
        repository: ProjectRepository,
        *,
        access: AccessService,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.repository = repository
        self.clock = clock
        self.id_factory = id_factory
        self.access = access
        self.collaboration = CollaborationService(access.repository, access, clock)
        self.recommendations = RecommendationService(self.collaboration)

    def create(self, owner_id: UUID, draft: ProjectDraft) -> Project:
        project = self.repository.add(
            Project(
                id=self.id_factory(),
                owner_id=owner_id,
                name=draft.name,
                description=draft.description,
                objective=draft.objective,
                created_at=self.clock(),
                **draft.model_dump(exclude={"name", "description", "objective"}),
            )
        )
        return project.model_copy(update={"permissions": sorted(OWNER)})

    def list(
        self,
        owner_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
        q: str = "",
        status: str | None = None,
        tag: str | None = None,
        archived: bool = False,
    ) -> ProjectPage:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        q = q.strip()
        if len(q) > 120:
            raise ValueError("Invalid search")
        return self.access.list(
            owner_id, limit=limit, offset=offset, q=q, status=status, tag=tag, archived=archived
        )

    def get(self, owner_id: UUID, project_id: UUID) -> Project | None:
        return self.access.get(owner_id, project_id)

    def delete(self, owner_id: UUID, project_id: UUID) -> bool:
        return self.collaboration.delete_project(owner_id, project_id)

    def patch(self, owner_id: UUID, project_id: UUID, patch: ProjectPatch) -> Project | None:
        return self.access.patch_project(owner_id, project_id, patch)
