"""Stateless curation through current project access and session ports."""

from collections.abc import Callable
from uuid import UUID

from projects_service.access_domain import AccessError
from projects_service.module5_domain import CurationDraft, CurationResult


class CurationService:
    def __init__(
        self,
        *,
        enabled: bool,
        read_project: Callable[[UUID, UUID], None],
        reauthenticate: Callable[[], None],
        fetch_feed: Callable[[], CurationResult],
        search: Callable[[str], CurationResult],
    ) -> None:
        self.enabled = enabled
        self.read_project = read_project
        self.reauthenticate = reauthenticate
        self.fetch_feed = fetch_feed
        self.search = search

    def feed(self, actor: UUID, project_id: UUID) -> CurationResult:
        self.read_project(actor, project_id)
        if not self.enabled:
            return CurationResult(enabled=False)
        return self._retrieve(actor, project_id, self.fetch_feed)

    def query(self, actor: UUID, project_id: UUID, draft: CurationDraft) -> CurationResult:
        self.read_project(actor, project_id)
        if not self.enabled:
            raise AccessError(503, "Project curation is disabled")
        return self._retrieve(actor, project_id, lambda: self.search(draft.pergunta))

    def _retrieve(
        self, actor: UUID, project_id: UUID, fetch: Callable[[], CurationResult]
    ) -> CurationResult:
        try:
            return fetch()
        finally:
            self.reauthenticate()
            self.read_project(actor, project_id)
