"""Artifact use cases with fresh access/session/binding checks around network I/O."""

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from projects_service.access_domain import AccessError
from projects_service.module3_domain import (
    ArtifactCatalog,
    ArtifactDownload,
    ArtifactPage,
    VersionPage,
)

T = TypeVar("T")


class ArtifactsService:
    def __init__(
        self,
        *,
        enabled: bool,
        read_binding: Callable[[UUID, UUID], int | None],
        reauthenticate: Callable[[], None],
        fetch_catalog: Callable[[], ArtifactCatalog],
        fetch_artifacts: Callable[[int, str, str], ArtifactPage],
        fetch_versions: Callable[[int, int], VersionPage],
        fetch_download: Callable[[int, int], ArtifactDownload],
    ) -> None:
        self.enabled = enabled
        self.read_binding = read_binding
        self.reauthenticate = reauthenticate
        self.fetch_catalog = fetch_catalog
        self.fetch_artifacts = fetch_artifacts
        self.fetch_versions = fetch_versions
        self.fetch_download = fetch_download

    def _retrieve(
        self,
        actor: UUID,
        project_id: UUID,
        binding: int | None,
        fetch: Callable[[], T],
    ) -> T:
        try:
            return fetch()
        finally:
            self.reauthenticate()
            if self.read_binding(actor, project_id) != binding:
                raise AccessError(409, "Artifact project association changed; refresh")

    def catalog(self, actor: UUID, project_id: UUID) -> ArtifactCatalog:
        binding = self.read_binding(actor, project_id)
        if not self.enabled:
            return ArtifactCatalog(enabled=False)
        return self._retrieve(actor, project_id, binding, self.fetch_catalog)

    def artifacts(
        self,
        actor: UUID,
        project_id: UUID,
        search: str = "",
        artifact_type: str = "",
    ) -> ArtifactPage:
        binding = self.read_binding(actor, project_id)
        if not self.enabled or binding is None:
            return ArtifactPage(enabled=self.enabled, module3_project_id=binding)
        return self._retrieve(
            actor, project_id, binding, lambda: self.fetch_artifacts(binding, search, artifact_type)
        )

    def _linked(self, actor: UUID, project_id: UUID, expected: int) -> int:
        binding = self.read_binding(actor, project_id)
        if not self.enabled:
            raise AccessError(503, "Artifact service is disabled")
        if binding is None:
            raise AccessError(404, "Artifact project is not associated")
        if binding != expected:
            raise AccessError(409, "Artifact project association changed; refresh")
        return binding

    def versions(
        self,
        actor: UUID,
        project_id: UUID,
        artifact_id: int,
        expected: int,
    ) -> VersionPage:
        binding = self._linked(actor, project_id, expected)
        return self._retrieve(
            actor, project_id, binding, lambda: self.fetch_versions(binding, artifact_id)
        )

    def download(
        self,
        actor: UUID,
        project_id: UUID,
        artifact_id: int,
        expected: int,
    ) -> ArtifactDownload:
        binding = self._linked(actor, project_id, expected)
        return self._retrieve(
            actor, project_id, binding, lambda: self.fetch_download(binding, artifact_id)
        )
