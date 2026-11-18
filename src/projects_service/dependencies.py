import asyncio
from collections.abc import Callable, Iterator
from datetime import datetime
from functools import partial
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from projects_service.access_service import AccessService
from projects_service.collaboration_repository import CollaborationRepository
from projects_service.module5_client import Module5Client
from projects_service.module5_service import CurationService
from projects_service.repository import ProjectRepository
from projects_service.security import AuthenticationRejected, SigningKeysUnavailable
from projects_service.service import ProjectsService, utc_now


def build_projects_service(
    session: Session,
    *,
    clock: Callable[[], datetime] = utc_now,
    id_factory: Callable[[], UUID] = uuid4,
) -> ProjectsService:
    return ProjectsService(
        ProjectRepository(session),
        access=AccessService(CollaborationRepository(session, clock=clock), clock),
        clock=clock,
        id_factory=id_factory,
    )


bearer = HTTPBearer(auto_error=False)


def authentication_required() -> HTTPException:
    return HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})


def verify_owner(request: Request, token: str, *, require_online: bool = False) -> UUID:
    try:
        owner: UUID = request.app.state.verifier.verify(token)
        if require_online or request.app.state.settings.auth_session_check_enabled:
            request.app.state.identity.check(token, owner)
        return owner
    except AuthenticationRejected:
        raise authentication_required() from None
    except SigningKeysUnavailable:
        raise HTTPException(503, "Service temporarily unavailable") from None


def observe_project_access(request: Request, owner: UUID) -> None:
    parts = request.url.path.strip("/").split("/")
    if len(parts) < 2 or parts[0] != "projects":
        return
    try:
        project_id = UUID(parts[1])
    except ValueError:
        return
    with Session(request.app.state.callback_engine, expire_on_commit=False) as activity_session:
        activity = build_projects_service(activity_session, clock=request.app.state.clock)
        activity.collaboration.observe_access(owner, project_id)


Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def current_owner(request: Request, credentials: Credentials) -> UUID:
    if credentials is None:
        raise authentication_required()
    owner = verify_owner(request, credentials.credentials)
    observe_project_access(request, owner)
    return owner


def current_curation_actor(request: Request, credentials: Credentials) -> UUID:
    if credentials is None:
        raise authentication_required()
    actor = verify_owner(request, credentials.credentials, require_online=True)
    observe_project_access(request, actor)
    return actor


CurationActor = Annotated[UUID, Depends(current_curation_actor)]


async def curation_service(
    request: Request, actor: CurationActor, credentials: Credentials
) -> CurationService:
    assert credentials is not None
    token = credentials.credentials
    loop = asyncio.get_running_loop()
    client: Module5Client = request.app.state.module5

    def read_project(user: UUID, project_id: UUID) -> None:
        # Exiting this read scope releases the connection before any remote I/O.
        with Session(request.app.state.engine) as session:
            service = build_projects_service(session, clock=request.app.state.clock)
            service.access.access(user, project_id)

    def reauthenticate() -> None:
        if verify_owner(request, token, require_online=True) != actor:
            raise authentication_required()

    return CurationService(
        enabled=request.app.state.settings.module5_enabled,
        read_project=read_project,
        reauthenticate=reauthenticate,
        fetch_feed=partial(client.feed, loop=loop),
        search=partial(client.query, token, loop=loop),
    )


Curation = Annotated[CurationService, Depends(curation_service)]


def project_service(request: Request) -> Iterator[ProjectsService]:
    authorization_callback = request.url.path.startswith(
        "/projects/"
    ) and request.url.path.endswith(("/access", "/access/v2", "/eligibility"))
    engine = (
        request.app.state.callback_engine if authorization_callback else request.app.state.engine
    )
    with Session(engine, expire_on_commit=False) as session:
        service = build_projects_service(session, clock=request.app.state.clock)
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        service.collaboration.identity_active = lambda target: request.app.state.identity.active(
            token, target
        )
        service.collaboration.backlog_summary = lambda project_id: (
            request.app.state.backlog.summary(token, project_id)
        )
        service.collaboration.backlog_items = lambda project_id: (
            request.app.state.backlog.items_snapshot(token, project_id)
        )
        service.collaboration.directory = lambda: request.app.state.identity.directory(token)
        service.collaboration.profile = lambda target: request.app.state.identity.profile(
            token, target
        )
        service.recommendations.generate = request.app.state.ai.generate
        service.recommendations.inactivity_days = request.app.state.settings.access_inactivity_days
        yield service


Owner = Annotated[UUID, Depends(current_owner)]
Service = Annotated[ProjectsService, Depends(project_service)]
