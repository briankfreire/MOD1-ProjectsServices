from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from projects_service.access_service import AccessService
from projects_service.collaboration_repository import CollaborationRepository
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


def current_owner(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> UUID:
    if credentials is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        owner: UUID = request.app.state.verifier.verify(credentials.credentials)
        if request.app.state.settings.auth_session_check_enabled:
            request.app.state.identity.check(credentials.credentials, owner)
        parts = request.url.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "projects":
            try:
                project_id = UUID(parts[1])
            except ValueError:
                project_id = None
            if project_id is not None:
                with Session(
                    request.app.state.callback_engine, expire_on_commit=False
                ) as activity_session:
                    activity = build_projects_service(
                        activity_session, clock=request.app.state.clock
                    )
                    activity.collaboration.observe_access(owner, project_id)
        return owner
    except AuthenticationRejected:
        raise HTTPException(
            401, "Authentication required", headers={"WWW-Authenticate": "Bearer"}
        ) from None
    except SigningKeysUnavailable:
        raise HTTPException(503, "Service temporarily unavailable") from None


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
