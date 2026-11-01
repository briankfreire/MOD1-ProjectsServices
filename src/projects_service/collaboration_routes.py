"""HTTP adapters for collaboration use cases."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Response

from projects_service.access_domain import InvitationAction
from projects_service.collaboration_domain import (
    AllocationDraft,
    EmptyAction,
    LeaseDraft,
    MemberDraft,
    RecommendationDraft,
    RoleDraft,
    RolePatch,
    TeamDraft,
    TeamInvite,
    TeamLink,
    TeamMemberDraft,
    TeamPatch,
)
from projects_service.dependencies import Owner, Service
from projects_service.domain import TransferAction, VersionAction

router = APIRouter()
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.post("/projects/{project_id}/roles", status_code=201)
def create_role(project_id: UUID, body: RoleDraft, owner: Owner, service: Service) -> Any:
    return service.collaboration.role(owner, project_id, None, body)


@router.patch("/projects/{project_id}/roles/{key}")
def patch_role(project_id: UUID, key: str, body: RolePatch, owner: Owner, service: Service) -> Any:
    return service.collaboration.role(owner, project_id, key, body)


@router.delete("/projects/{project_id}/roles/{key}", status_code=204, response_class=Response)
def delete_role(project_id: UUID, key: str, owner: Owner, service: Service) -> Response:
    service.collaboration.role(owner, project_id, key, None)
    return Response(status_code=204)


@router.post("/projects/{project_id}/members", status_code=201)
def add_member(project_id: UUID, body: MemberDraft, owner: Owner, service: Service) -> Any:
    return service.collaboration.add_member(owner, project_id, body)


@router.get("/projects/{project_id}/members/{user_id}/eligibility")
def eligibility(project_id: UUID, user_id: UUID, owner: Owner, service: Service) -> Any:
    return service.collaboration.eligibility(owner, project_id, user_id)


@router.post("/teams", status_code=201)
def create_team(body: TeamDraft, owner: Owner, service: Service) -> Any:
    return service.collaboration.create_team(owner, body)


@router.get("/teams")
def teams(owner: Owner, service: Service, limit: Limit = 20, offset: Offset = 0) -> Any:
    return service.collaboration.list_teams(owner, limit, offset)


@router.get("/teams/{team_id}")
def team(team_id: UUID, owner: Owner, service: Service) -> Any:
    return service.collaboration.get_team(owner, team_id)


@router.patch("/teams/{team_id}")
def patch_team(team_id: UUID, body: TeamPatch, owner: Owner, service: Service) -> Any:
    return service.collaboration.patch_team(owner, team_id, body)


@router.get("/teams/{team_id}/members")
def team_members(team_id: UUID, owner: Owner, service: Service) -> Any:
    return service.collaboration.team_members(owner, team_id)


@router.post("/teams/{team_id}/members", status_code=201)
def team_member(team_id: UUID, body: TeamMemberDraft, owner: Owner, service: Service) -> Any:
    return service.collaboration.team_member(owner, team_id, body.user_id, body)


@router.delete("/teams/{team_id}/members/{user_id}", status_code=204, response_class=Response)
def delete_team_member(team_id: UUID, user_id: UUID, owner: Owner, service: Service) -> Response:
    service.collaboration.team_member(owner, team_id, user_id, None)
    return Response(status_code=204)


@router.post("/teams/{team_id}/invitations", status_code=201)
def invite_team(team_id: UUID, body: TeamInvite, owner: Owner, service: Service) -> Any:
    return service.collaboration.invite_team(owner, team_id, body)


@router.post("/team-invitations/accept")
def accept_team(body: InvitationAction, owner: Owner, service: Service) -> Any:
    return service.collaboration.consume_team(owner, body.code, True)


@router.post("/team-invitations/decline", status_code=204, response_class=Response)
def decline_team(body: InvitationAction, owner: Owner, service: Service) -> Response:
    service.collaboration.consume_team(owner, body.code, False)
    return Response(status_code=204)


@router.get("/projects/{project_id}/teams")
def project_teams(project_id: UUID, owner: Owner, service: Service) -> Any:
    return service.collaboration.project_teams(owner, project_id)


@router.post("/projects/{project_id}/teams", status_code=201)
def link_team(project_id: UUID, body: TeamLink, owner: Owner, service: Service) -> Any:
    return service.collaboration.link_team(owner, project_id, body.team_id, body)


@router.delete("/projects/{project_id}/teams/{team_id}", status_code=204, response_class=Response)
def unlink_team(project_id: UUID, team_id: UUID, owner: Owner, service: Service) -> Response:
    service.collaboration.link_team(owner, project_id, team_id, None)
    return Response(status_code=204)


@router.post("/projects/{project_id}/write-leases")
def lease(project_id: UUID, body: LeaseDraft, owner: Owner, service: Service) -> Any:
    return service.collaboration.lease(owner, project_id, body.operation_id)


@router.delete(
    "/projects/{project_id}/write-leases/{lease_id}", status_code=204, response_class=Response
)
def release(project_id: UUID, lease_id: UUID, owner: Owner, service: Service) -> Response:
    service.collaboration.release_lease(owner, project_id, lease_id)
    return Response(status_code=204)


@router.post("/projects/{project_id}/transfer")
def transfer(project_id: UUID, body: TransferAction, owner: Owner, service: Service) -> Any:
    return service.collaboration.transfer(owner, project_id, body.user_id, body.expected_version)


@router.get("/projects/{project_id}/summary")
def summary(project_id: UUID, owner: Owner, service: Service) -> Any:
    return service.collaboration.summary(owner, project_id)


@router.get("/allocations/me")
def allocations_me(owner: Owner, service: Service) -> Any:
    return service.collaboration.allocations_me(owner)


@router.get("/projects/{project_id}/allocations")
def allocations(project_id: UUID, owner: Owner, service: Service) -> Any:
    return service.collaboration.allocation(owner, project_id, None)


@router.put("/projects/{project_id}/allocations")
def allocation(project_id: UUID, body: AllocationDraft, owner: Owner, service: Service) -> Any:
    return service.collaboration.allocation(owner, project_id, body)


@router.post("/projects/{project_id}/recommendations", status_code=201)
def recommend(project_id: UUID, body: RecommendationDraft, owner: Owner, service: Service) -> Any:
    return service.recommendations.create(owner, project_id, body)


@router.get("/projects/{project_id}/recommendations")
def recommendations(
    project_id: UUID, owner: Owner, service: Service, limit: Limit = 20, offset: Offset = 0
) -> Any:
    return service.recommendations.list(owner, project_id, limit, offset)


@router.get("/projects/{project_id}/recommendations/{recommendation_id}")
def recommendation(
    project_id: UUID, recommendation_id: UUID, owner: Owner, service: Service
) -> Any:
    return service.recommendations.get(owner, project_id, recommendation_id)


@router.post("/projects/{project_id}/recommendations/{recommendation_id}/approve")
def approve(
    project_id: UUID, recommendation_id: UUID, body: VersionAction, owner: Owner, service: Service
) -> Any:
    return service.recommendations.decide(
        owner, project_id, recommendation_id, body.expected_version, True
    )


@router.post("/projects/{project_id}/recommendations/{recommendation_id}/reject")
def reject(
    project_id: UUID, recommendation_id: UUID, body: VersionAction, owner: Owner, service: Service
) -> Any:
    return service.recommendations.decide(
        owner, project_id, recommendation_id, body.expected_version, False
    )


@router.get("/notifications")
def notifications(owner: Owner, service: Service, limit: Limit = 20, offset: Offset = 0) -> Any:
    return service.collaboration.notifications(owner, limit, offset)


@router.post("/notifications/{notification_id}/read")
def read_notification(
    notification_id: UUID, body: EmptyAction, owner: Owner, service: Service
) -> Any:
    return service.collaboration.read_notification(owner, notification_id)
