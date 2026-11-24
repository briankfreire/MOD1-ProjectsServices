"""Project-scoped read-only artifact presentation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response
from pydantic import BeforeValidator

from projects_service.dependencies import Artifacts, CurationActor
from projects_service.module3_domain import ArtifactCatalog, ArtifactPage, ArtifactType, VersionPage

router = APIRouter(prefix="/projects/{project_id}/artifacts", tags=["artifacts"])
ArtifactId = Annotated[int, Path(ge=1, le=9007199254740991)]
ExpectedBinding = Annotated[int, Query(ge=1, le=9007199254740991)]


@router.get("/catalog", response_model=ArtifactCatalog)
def catalog(project_id: UUID, actor: CurationActor, service: Artifacts) -> ArtifactCatalog:
    return service.catalog(actor, project_id)


@router.get("", response_model=ArtifactPage)
def artifacts(
    project_id: UUID,
    actor: CurationActor,
    service: Artifacts,
    search: Annotated[str, Query(max_length=120), BeforeValidator(str.strip)] = "",
    artifact_type: ArtifactType | None = None,
) -> ArtifactPage:
    return service.artifacts(actor, project_id, search, artifact_type or "")


@router.get("/{artifact_id}/versions", response_model=VersionPage)
def versions(
    project_id: UUID,
    artifact_id: ArtifactId,
    module3_project_id: ExpectedBinding,
    actor: CurationActor,
    service: Artifacts,
) -> VersionPage:
    return service.versions(actor, project_id, artifact_id, module3_project_id)


@router.get(
    "/{artifact_id}/download",
    response_class=Response,
    responses={
        200: {
            "description": "Current artifact version as a bounded attachment",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
def download(
    project_id: UUID,
    artifact_id: ArtifactId,
    module3_project_id: ExpectedBinding,
    actor: CurationActor,
    service: Artifacts,
) -> Response:
    result = service.download(actor, project_id, artifact_id, module3_project_id)
    return Response(
        result.content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="' + result.filename + '"',
            "X-Content-Type-Options": "nosniff",
        },
    )
