from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BeforeValidator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from projects_service.domain import Project, ProjectDraft, ProjectPage, ProjectPatch
from projects_service.models import ProjectRecord
from projects_service.repository import ProjectRepository
from projects_service.security import AuthenticationRejected, SigningKeysUnavailable
from projects_service.service import ProjectsService

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


def current_owner(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> UUID:
    if credentials is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        owner: UUID = request.app.state.verifier.verify(credentials.credentials)
        return owner
    except AuthenticationRejected:
        raise HTTPException(
            401, "Authentication required", headers={"WWW-Authenticate": "Bearer"}
        ) from None
    except SigningKeysUnavailable:
        raise HTTPException(503, "Service temporarily unavailable") from None


def project_service(request: Request) -> Iterator[ProjectsService]:
    with Session(request.app.state.engine, expire_on_commit=False) as session:
        yield ProjectsService(ProjectRepository(session))


Owner = Annotated[UUID, Depends(current_owner)]
Service = Annotated[ProjectsService, Depends(project_service)]


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
) -> ProjectPage:
    return service.list(owner, limit=limit, offset=offset, q=q)


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
        401: {"description": "Authentication required"},
        404: {"description": "Project unavailable (missing or not owned by the caller)"},
        422: {"description": "Invalid project input"},
        503: {"description": "Service temporarily unavailable"},
    },
    description=(
        "Deletes only the caller's project. Backlog stories are retained but subsequent "
        "backlog operations are denied. External links belong to their respective services; "
        "this operation does not delete GitHub resources. Repeating a deletion returns 404."
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
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(select(ProjectRecord.id).limit(1))
    except SQLAlchemyError:
        raise HTTPException(503, "Service temporarily unavailable") from None
    return {"status": "ready"}
