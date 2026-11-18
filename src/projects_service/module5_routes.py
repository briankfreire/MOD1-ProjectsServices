"""Project curation HTTP endpoints."""

from uuid import UUID

from fastapi import APIRouter

from projects_service.dependencies import Curation, CurationActor
from projects_service.module5_domain import CurationDraft, CurationResult

router = APIRouter(prefix="/projects/{project_id}/curation", tags=["curation"])


@router.get("/feed", response_model=CurationResult)
def feed(project_id: UUID, actor: CurationActor, service: Curation) -> CurationResult:
    return service.feed(actor, project_id)


@router.post("/queries", response_model=CurationResult)
def query(
    project_id: UUID, draft: CurationDraft, actor: CurationActor, service: Curation
) -> CurationResult:
    return service.query(actor, project_id, draft)
