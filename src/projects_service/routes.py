from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, BeforeValidator

from projects_service.dependencies import Owner, Service
from projects_service.domain import (
    LifecycleAction,
    Project,
    ProjectDraft,
    ProjectPage,
    ProjectPatch,
    VersionAction,
)
from projects_service.readiness import database_ready

router = APIRouter()


class ProjectErrorResponse(BaseModel):
    detail: str


@router.post("/projects", response_model=Project, status_code=201)
def create_project(draft: ProjectDraft, owner: Owner, service: Service) -> Project:
    return service.create(owner, draft)


@router.get("/projects", response_model=ProjectPage)
def list_projects(
    owner: Owner,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str, Query(max_length=120), BeforeValidator(str.strip)] = "",
    status: str | None = None,
    tag: str | None = None,
    archived: bool = False,
) -> ProjectPage:
    page = service.list(
        owner, limit=limit, offset=offset, q=q, status=status, tag=tag, archived=archived
    )
    for project in page.items:
        service.collaboration.observe_access(owner, project.id)
    return page


@router.get("/projects/{project_id}", response_model=Project)
def get_project(project_id: UUID, owner: Owner, service: Service) -> Project:
    project = service.get(owner, project_id)
    if project is None:
        raise HTTPException(404, "Project unavailable")
    return project


@router.patch(
    "/projects/{project_id}",
    response_model=Project,
    responses={
        401: {"description": "Authentication required"},
        404: {"description": "Project unavailable (missing or not owned by the caller)"},
        422: {"description": "Invalid project input"},
        503: {"description": "Service temporarily unavailable"},
    },
)
def patch_project(project_id: UUID, patch: ProjectPatch, owner: Owner, service: Service) -> Project:
    project = service.patch(owner, project_id, patch)
    if project is None:
        raise HTTPException(404, "Project unavailable")
    return project


@router.delete(
    "/projects/{project_id}",
    status_code=204,
    response_class=Response,
    responses={
        204: {"description": "Empty project deleted; no response body"},
        401: {
            "description": "Bearer authentication required or rejected",
            "model": ProjectErrorResponse,
        },
        403: {
            "description": "Visible project; caller is not the owner",
            "model": ProjectErrorResponse,
        },
        404: {
            "description": "Project missing or inaccessible, including repeat deletion",
            "model": ProjectErrorResponse,
        },
        409: {
            "description": "Relevant content, links/history, or active writes prevent deletion",
            "model": ProjectErrorResponse,
        },
        422: {"description": "Invalid project identifier", "model": ProjectErrorResponse},
        503: {
            "description": "Database, identity, keys, or backlog unavailable/inconsistent",
            "model": ProjectErrorResponse,
        },
    },
    description=(
        "Deletes an empty project only, using the same Bearer and owner permission; "
        "no request body. "
        "Rejects relevant local links/history or active writes and verifies the Backlog content "
        "summary before deletion. Backlog stories, epics, tasks, history, recommendations and "
        "review events are not deleted in cascade: existing content prevents deletion with 409. "
        "Prefer archiving completed projects that contain work. This operation does not delete "
        "GitHub repositories or external links, nor verify other modules' references. "
        "On 204, do not parse JSON. Repeating a deletion returns 404. After a timeout or uncertain "
        "response, reconcile with GET before retrying; "
        "a 503 does not prove an earlier commit failed."
    ),
)
def delete_project(project_id: UUID, owner: Owner, service: Service) -> Response:
    if not service.delete(owner, project_id):
        raise HTTPException(404, "Project unavailable")
    return Response(status_code=204)


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
def ready(request: Request) -> dict[str, str]:
    if not database_ready(request.app.state.engine):
        raise HTTPException(503, "Service temporarily unavailable")
    return {"status": "ready"}


@router.post("/projects/{project_id}/lifecycle", response_model=Project)
def lifecycle(project_id: UUID, body: LifecycleAction, owner: Owner, service: Service) -> Project:
    return service.access.lifecycle(owner, project_id, body.expected_version, status=body.status)


@router.post("/projects/{project_id}/archive", response_model=Project)
def archive(project_id: UUID, body: VersionAction, owner: Owner, service: Service) -> Project:
    return service.access.lifecycle(owner, project_id, body.expected_version, archive=True)


@router.post("/projects/{project_id}/restore", response_model=Project)
def restore(project_id: UUID, body: VersionAction, owner: Owner, service: Service) -> Project:
    return service.access.lifecycle(owner, project_id, body.expected_version, archive=False)


@router.get("/projects/{project_id}/history")
def history(
    project_id: UUID,
    owner: Owner,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: str = "",
) -> dict[str, object]:
    return service.access.history(owner, project_id, limit, offset, action)


@router.get("/projects/{project_id}/audit")
def audit(
    project_id: UUID,
    owner: Owner,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: str = "",
) -> dict[str, object]:
    return service.access.history(owner, project_id, limit, offset, action or "access.")


@router.get("/projects/{project_id}/access/v2")
def access_v2(project_id: UUID, owner: Owner, service: Service) -> dict[str, object]:
    return service.access.access_v2(owner, project_id)
