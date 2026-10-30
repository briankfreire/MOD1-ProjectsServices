from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from projects_service.access_domain import (
    Access,
    InvitationAction,
    InvitationCreated,
    InvitationDraft,
    Member,
    MemberPage,
    MembershipPatch,
    RolePage,
)
from projects_service.routes import Owner, Service

router = APIRouter()


@router.get("/projects/{project_id}/access", response_model=Access)
def access(project_id: UUID, owner: Owner, service: Service) -> Access:
    return service.access.access(owner, project_id)


@router.get("/projects/{project_id}/roles", response_model=RolePage)
def roles(project_id: UUID, owner: Owner, service: Service) -> RolePage:
    return service.access.roles(owner, project_id)


@router.get("/projects/{project_id}/members", response_model=MemberPage)
def members(
    project_id: UUID,
    owner: Owner,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MemberPage:
    return service.access.members(owner, project_id, limit=limit, offset=offset)


@router.patch("/projects/{project_id}/members/{user_id}", response_model=Member)
def patch_member(
    project_id: UUID, user_id: UUID, patch: MembershipPatch, owner: Owner, service: Service
) -> Member:
    member = service.access.change_member(owner, project_id, user_id, patch)
    assert member is not None
    return member


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204, response_class=Response)
def remove_member(project_id: UUID, user_id: UUID, owner: Owner, service: Service) -> Response:
    service.access.change_member(owner, project_id, user_id, None)
    return Response(status_code=204)


@router.post(
    "/projects/{project_id}/invitations", response_model=InvitationCreated, status_code=201
)
def invite(
    project_id: UUID, draft: InvitationDraft, owner: Owner, service: Service
) -> InvitationCreated:
    return service.access.invite(owner, project_id, draft)


@router.post("/invitations/accept", response_model=Access)
def accept(body: InvitationAction, owner: Owner, service: Service) -> Access:
    access = service.access.consume(owner, body.code, accept=True)
    assert access is not None
    return access


@router.post("/invitations/decline", status_code=204, response_class=Response)
def decline(body: InvitationAction, owner: Owner, service: Service) -> Response:
    service.access.consume(owner, body.code, accept=False)
    return Response(status_code=204)
