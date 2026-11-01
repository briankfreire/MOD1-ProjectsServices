from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from projects_service.app import create_app
from projects_service.database import init_schema


@pytest.fixture
def client(issuer):
    app = create_app(issuer["settings"])
    init_schema(app.state.engine, "projects")
    app.state.identity.active = lambda token, target: True
    app.state.identity.profile = lambda token, target: None
    app.state.backlog.items_snapshot = lambda token, project_id: []
    with TestClient(app) as client:
        yield client


def auth(issuer, user=None):
    return {"Authorization": "Bearer " + issuer["token"](sub=user)}


def create(client, issuer, **fields):
    response = client.post("/projects", json={"name": "Advanced", **fields}, headers=auth(issuer))
    assert response.status_code == 201, response.text
    return response.json()


def test_metadata_lifecycle_version_and_write_guards(client, issuer):
    project = create(
        client,
        issuer,
        scope="Scope",
        budget_amount="1250.50",
        tags=["api"],
        planned_start="2026-11-01",
        planned_end="2026-12-01",
        technology_stack=["Python"],
        technical_requirements=["REST"],
    )
    assert project["status"] == "planned"
    assert project["budget_amount"] == "1250.50"
    path = "/projects/" + project["id"]
    suspended = client.post(
        path + "/lifecycle",
        json={"status": "suspended", "expected_version": 1},
        headers=auth(issuer),
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["version"] == 2
    assert client.patch(path, json={"scope": "No"}, headers=auth(issuer)).status_code == 409
    assert (
        client.post(
            path + "/lifecycle",
            json={"status": "active", "expected_version": 1},
            headers=auth(issuer),
        ).status_code
        == 409
    )
    done = client.post(
        path + "/lifecycle",
        json={"status": "completed", "expected_version": 2},
        headers=auth(issuer),
    )
    assert done.status_code == 200
    archived = client.post(path + "/archive", json={"expected_version": 3}, headers=auth(issuer))
    assert archived.json()["archived"] is True
    assert client.get("/projects", headers=auth(issuer)).json()["total"] == 0
    assert client.get("/projects?archived=true&tag=api", headers=auth(issuer)).json()["total"] == 1
    assert (
        client.post(path + "/restore", json={"expected_version": 4}, headers=auth(issuer)).json()[
            "status"
        ]
        == "completed"
    )
    history = client.get(path + "/history", headers=auth(issuer)).json()
    assert history["total"] == 5
    access = client.get(path + "/access/v2", headers=auth(issuer)).json()
    assert access["access_version"] == 2 and access["project_status"] == "completed"


@pytest.mark.parametrize(
    "fields",
    [
        {"budget_amount": "-1"},
        {"budget_amount": 1.1},
        {"planned_start": "2026-12-01", "planned_end": "2026-11-01"},
        {"tags": ["x"] * 31},
        {"budget_currency": "invalid"},
    ],
)
def test_metadata_rejects_invalid_values(client, issuer, fields):
    assert (
        client.post("/projects", json={"name": "A", **fields}, headers=auth(issuer)).status_code
        == 422
    )


def test_authoritative_identity_rejects_revoked_and_mismatched_state(issuer):
    from projects_service.integrations import IdentityStatusClient

    settings = issuer["settings"].model_copy(update={"auth_session_check_enabled": True})
    app = create_app(settings)
    init_schema(app.state.engine, "projects")
    state = {"status": 401, "body": {}}

    def handler(request):
        assert request.url.path == "/auth/me"
        assert request.headers["authorization"].startswith("Bearer ")
        return httpx.Response(state["status"], json=state["body"])

    app.state.identity = IdentityStatusClient(
        settings, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with TestClient(app) as client:
        assert client.get("/projects", headers=auth(issuer)).status_code == 401
        state.update(status=200, body={"id": str(uuid4()), "is_active": True})
        assert client.get("/projects", headers=auth(issuer)).status_code == 503
        state["body"]["id"] = str(issuer["owner"])
        assert client.get("/projects", headers=auth(issuer)).status_code == 200
        state["body"]["is_active"] = False
        assert client.get("/projects", headers=auth(issuer)).status_code == 401


def test_custom_roles_grant_expiry_team_inheritance_and_project_deny(client, issuer):
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    headers = auth(issuer)
    user = uuid4()
    role = client.post(
        path + "/roles",
        json={
            "name": "Analyst",
            "permissions": ["project:read", "project:members:read", "backlog:read"],
        },
        headers=headers,
    )
    assert role.status_code == 201, role.text
    key = role.json()["key"]
    assert (
        client.post(
            path + "/roles",
            json={"name": "Unsafe", "permissions": ["project:delete"]},
            headers=headers,
        ).status_code
        == 422
    )
    team = client.post("/teams", json={"name": "Delivery", "cost_center": "CC-1"}, headers=headers)
    assert team.status_code == 201
    team_path = "/teams/" + team.json()["id"]
    assert (
        client.post(
            team_path + "/members",
            json={"user_id": str(user), "is_manager": False},
            headers=headers,
        ).status_code
        == 201
    )
    linked = client.post(
        path + "/teams", json={"team_id": team.json()["id"], "roles": [key]}, headers=headers
    )
    assert linked.status_code == 201, linked.text
    user_access = client.get(path + "/access/v2", headers=auth(issuer, user))
    assert user_access.status_code == 200, user_access.text
    assert user_access.json()["origins"][0]["type"] == "team"
    assert client.get("/projects", headers=auth(issuer, user)).json()["total"] == 1
    assert client.delete(path + "/roles/" + key, headers=headers).status_code == 409
    assert client.delete(path + "/members/" + str(user), headers=headers).status_code == 204
    assert client.get(path, headers=auth(issuer, user)).status_code == 404
    assert client.get(team_path, headers=auth(issuer, user)).status_code == 200
    assert (
        client.post(
            path + "/members",
            json={
                "user_id": str(user),
                "roles": ["developer"],
                "role_grants": [
                    {
                        "role": "developer",
                        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                    }
                ],
            },
            headers=headers,
        ).status_code
        == 201
    )
    assert client.get(path, headers=auth(issuer, user)).status_code == 200
    assert client.get(path + "/audit", headers=headers).json()["total"] >= 3


def test_team_invitation_is_recipient_bound_single_use_and_cost_private(client, issuer):
    headers = auth(issuer)
    user = uuid4()
    team = client.post("/teams", json={"name": "A"}, headers=headers)
    assert team.status_code == 201
    path = "/teams/" + team.json()["id"]
    invitation = client.post(path + "/invitations", json={"user_id": str(user)}, headers=headers)
    assert invitation.status_code == 201
    body = {"code": invitation.json()["code"]}
    assert (
        client.post(
            "/team-invitations/accept", json=body, headers=auth(issuer, uuid4())
        ).status_code
        == 404
    )
    assert (
        client.post("/team-invitations/accept", json=body, headers=auth(issuer, user)).status_code
        == 200
    )
    assert (
        client.post("/team-invitations/accept", json=body, headers=auth(issuer, user)).status_code
        == 404
    )
    assert (
        client.patch(path, json={"cost_center": "Private"}, headers=auth(issuer, user)).status_code
        == 403
    )


def test_write_leases_gate_deletion_and_freeze_closes_race(client, issuer):
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    headers = auth(issuer)
    operation = {"operation_id": str(uuid4())}
    lease = client.post(path + "/write-leases", json=operation, headers=headers)
    assert lease.status_code == 200, lease.text
    assert (
        client.post(path + "/write-leases", json=operation, headers=headers).json() == lease.json()
    )
    assert client.delete(path, headers=headers).status_code == 409
    assert (
        client.delete(
            path + "/write-leases/" + lease.json()["lease_id"], headers=auth(issuer, uuid4())
        ).status_code
        == 404
    )
    assert (
        client.delete(
            path + "/write-leases/" + lease.json()["lease_id"], headers=headers
        ).status_code
        == 204
    )

    def summary(token, project_id):
        blocked = client.post(
            path + "/write-leases", json={"operation_id": str(uuid4())}, headers=headers
        )
        assert blocked.status_code == 409
        return {
            "project_id": str(project_id),
            "stories": 0,
            "epics": 0,
            "tasks": 0,
            "history": 0,
            "total": 0,
        }

    client.app.state.backlog.summary = summary
    assert client.delete(path, headers=headers).status_code == 204


def test_safe_delete_refuses_relevant_content_and_dependency_failure_unfreezes(client, issuer):
    from projects_service.access_domain import AccessError

    project = create(client, issuer)
    path = "/projects/" + project["id"]
    headers = auth(issuer)

    def unavailable(*args):
        raise AccessError(503, "Backlog temporarily unavailable")

    client.app.state.backlog.summary = unavailable
    assert client.delete(path, headers=headers).status_code == 503
    assert (
        client.post(
            path + "/write-leases", json={"operation_id": str(uuid4())}, headers=headers
        ).status_code
        == 200
    )
    project2 = create(client, issuer)
    path2 = "/projects/" + project2["id"]
    client.app.state.backlog.summary = lambda token, pid: {
        "project_id": str(pid),
        "total": 1,
        "stories": 1,
        "epics": 0,
        "tasks": 0,
        "history": 0,
    }
    assert client.delete(path2, headers=headers).status_code == 409
    assert client.get(path2, headers=headers).status_code == 200


def test_transfer_allocations_eligibility_and_capacity_private(client, issuer):
    headers = auth(issuer)
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    target = uuid4()
    added = client.post(
        path + "/members", json={"user_id": str(target), "roles": ["developer"]}, headers=headers
    )
    assert added.status_code == 201
    eligible = client.get(path + "/members/" + str(target) + "/eligibility", headers=headers).json()
    assert eligible["eligible"] is True
    allocation = client.put(
        path + "/allocations",
        json={
            "user_id": str(target),
            "weekly_hours": "20",
            "hourly_rate": "75.50",
            "currency": "BRL",
        },
        headers=headers,
    )
    assert allocation.status_code == 200, allocation.text
    assert client.get(path + "/allocations", headers=auth(issuer, target)).status_code == 403
    mine = client.get("/allocations/me", headers=auth(issuer, target)).json()
    assert mine["total_allocated_hours"] == "20"
    assert mine["weekly_availability_hours"] is None
    version = client.get(path, headers=headers).json()["version"]
    transferred = client.post(
        path + "/transfer",
        json={"user_id": str(target), "expected_version": version},
        headers=headers,
    )
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["owner_id"] == str(target)
    assert client.get(path + "/access/v2", headers=headers).json()["roles"] == ["project_manager"]


def test_partial_dates_validate_against_stored_metadata(client, issuer):
    project = create(client, issuer, planned_start="2026-11-01", planned_end="2026-12-01")
    response = client.patch(
        "/projects/" + project["id"], json={"planned_start": "2027-01-01"}, headers=auth(issuer)
    )
    assert response.status_code == 422
    assert (
        client.get("/projects/" + project["id"], headers=auth(issuer)).json()["planned_start"]
        == "2026-11-01"
    )


def test_recommendations_are_authorized_validated_and_applied_once(client, issuer):
    from projects_service.integrations import AIClient

    headers = auth(issuer)
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    user = uuid4()
    client.app.state.identity.directory = lambda token: [
        {
            "user_id": str(user),
            "display_name": "Shared",
            "summary": "",
            "seniority": "mid",
            "weekly_availability_hours": 40,
            "skills": [{"name": "Python", "level": "advanced"}],
            "share_for_recommendations": True,
        }
    ]
    state = {"suggestions": [{"user_id": str(user), "roles": ["developer"]}]}

    def provider(request):
        import json

        body = json.loads(request.content)
        assert body["schema_version"] == 1 and body["kind"] == "roles"
        assert body["context"]["candidates"][0]["id"] == str(user)
        return httpx.Response(
            200,
            json={
                "summary": "Role draft",
                "justification": "Skill match",
                "evidence": ["profile:" + str(user)],
                "suggestions": state["suggestions"],
            },
        )

    settings = issuer["settings"].model_copy(
        update={"ai_base_url": "http://127.0.0.1:9999", "ai_model": "test", "ai_simulated": True}
    )
    client.app.state.ai = AIClient(
        settings, client=httpx.Client(transport=httpx.MockTransport(provider))
    )
    response = client.post(path + "/recommendations", json={"kind": "roles"}, headers=headers)
    assert response.status_code == 201, response.text
    recommendation = response.json()
    assert recommendation["simulated"] is True and recommendation["status"] == "pending"
    assert client.get(path + "/members", headers=headers).json()["total"] == 1
    rid = path + "/recommendations/" + recommendation["id"]
    approved = client.post(rid + "/approve", json={"expected_version": 1}, headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert (
        client.post(rid + "/approve", json={"expected_version": 1}, headers=headers).status_code
        == 200
    )
    assert client.get(path + "/members", headers=headers).json()["total"] == 2
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from projects_service.models import OutboxRecord

    with Session(client.app.state.engine) as session:
        assert session.scalar(select(func.count()).select_from(OutboxRecord)) == 1
    state["suggestions"] = [{"user_id": str(uuid4()), "roles": ["developer"]}]
    assert (
        client.post(path + "/recommendations", json={"kind": "roles"}, headers=headers).status_code
        == 503
    )


def test_recommendation_context_changes_and_disabled_provider_fail_closed(client, issuer):
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    headers = auth(issuer)
    assert (
        client.post(
            path + "/recommendations", json={"kind": "training"}, headers=headers
        ).status_code
        == 503
    )


def test_custom_read_only_role_can_read_access_v2_without_member_directory(client, issuer):
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    headers = auth(issuer)
    role = client.post(
        path + "/roles", json={"name": "Reader", "permissions": ["project:read"]}, headers=headers
    ).json()
    user = uuid4()
    assert (
        client.post(
            path + "/members", json={"user_id": str(user), "roles": [role["key"]]}, headers=headers
        ).status_code
        == 201
    )
    response = client.get(path + "/access/v2", headers=auth(issuer, user))
    assert response.status_code == 200
    assert response.json()["permissions"] == ["project:read"]
    assert client.get(path + "/members", headers=auth(issuer, user)).status_code == 403


def test_per_role_expiry_keeps_other_grants_and_expiry_survives_migration(client, issuer):
    from datetime import UTC, datetime

    client.app.state.clock = lambda: datetime(2026, 10, 30, tzinfo=UTC)
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    user = uuid4()
    added = client.post(
        path + "/members",
        json={
            "user_id": str(user),
            "roles": ["developer", "product_owner"],
            "role_grants": [
                {"role": "developer", "expires_at": None},
                {"role": "product_owner", "expires_at": "2026-10-31T00:00:00Z"},
            ],
        },
        headers=auth(issuer),
    )
    assert added.status_code == 201
    assert (
        "backlog:create"
        in client.get(path + "/access/v2", headers=auth(issuer, user)).json()["permissions"]
    )
    client.app.state.clock = lambda: datetime(2026, 11, 1, tzinfo=UTC)
    access = client.get(path + "/access/v2", headers=auth(issuer, user)).json()
    assert access["roles"] == ["developer"]
    assert "backlog:create" not in access["permissions"]


def test_project_create_event_failure_rolls_back_project(client, issuer):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError

    def fail_event(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO MAIN.EVENTS"):
            raise OperationalError(statement, parameters, Exception("synthetic"))

    engine = client.app.state.engine
    event.listen(engine, "before_cursor_execute", fail_event)
    try:
        response = client.post("/projects", json={"name": "Atomic"}, headers=auth(issuer))
        assert response.status_code == 503
    finally:
        event.remove(engine, "before_cursor_execute", fail_event)
    assert client.get("/projects", headers=auth(issuer)).json()["total"] == 0


def test_known_capacity_prevents_overallocation(client, issuer):
    headers = auth(issuer)
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    user = uuid4()
    client.app.state.identity.profile = lambda token, target: {
        "user_id": str(target),
        "weekly_availability_hours": 12,
    }
    assert (
        client.post(
            path + "/members", json={"user_id": str(user), "roles": ["developer"]}, headers=headers
        ).status_code
        == 201
    )
    response = client.put(
        path + "/allocations", json={"user_id": str(user), "weekly_hours": "20"}, headers=headers
    )
    assert response.status_code == 409
    assert client.get(path + "/allocations", headers=headers).json()["total"] == 0


def configure_provider(client, issuer, user, kind, suggestions):
    from projects_service.integrations import AIClient

    directory = [
        {
            "user_id": str(user),
            "display_name": "Shared",
            "summary": "",
            "seniority": "mid",
            "weekly_availability_hours": 40,
            "skills": [{"name": "Python", "level": "advanced"}],
            "share_for_recommendations": True,
        }
    ]
    client.app.state.identity.directory = lambda token: directory

    def provider(request):
        import json

        context = json.loads(request.content)["context"]
        return httpx.Response(
            200,
            json={
                "summary": kind,
                "justification": "Human review required",
                "evidence": context["evidence"][:1],
                "suggestions": suggestions,
            },
        )

    settings = issuer["settings"].model_copy(
        update={"ai_base_url": "http://127.0.0.1:9999", "ai_simulated": True}
    )
    client.app.state.ai = AIClient(
        settings, client=httpx.Client(transport=httpx.MockTransport(provider))
    )


@pytest.mark.parametrize("kind", ["roles", "access_revocation", "teams", "skills_map", "training"])
def test_all_recommendation_kinds_revalidate_and_require_explicit_approval(client, issuer, kind):
    from datetime import UTC, datetime

    if kind == "access_revocation":
        client.app.state.clock = lambda: datetime(2026, 9, 1, tzinfo=UTC)
    headers = auth(issuer)
    user = uuid4()
    project = create(client, issuer, technology_stack=["Python"])
    path = "/projects/" + project["id"]
    if kind == "access_revocation":
        assert (
            client.post(
                path + "/members",
                json={"user_id": str(user), "roles": ["developer"]},
                headers=headers,
            ).status_code
            == 201
        )
        client.app.state.clock = lambda: datetime(2026, 10, 2, tzinfo=UTC)
    suggestions = {
        "roles": [{"user_id": str(user), "roles": ["developer"]}],
        "access_revocation": [{"user_id": str(user), "reason": "Review access"}],
        "teams": [{"name": "Suggested team", "user_ids": [str(user)], "roles": ["developer"]}],
        "skills_map": [{"skill": "Python", "user_ids": [str(user)], "gap": False}],
        "training": [{"user_id": str(user), "topics": ["Python testing"]}],
    }[kind]
    configure_provider(client, issuer, user, kind, suggestions)
    response = client.post(path + "/recommendations", json={"kind": kind}, headers=headers)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["status"] == "pending"
    rid = path + "/recommendations/" + record["id"]
    approved = client.post(rid + "/approve", json={"expected_version": 1}, headers=headers)
    assert approved.status_code == 200, approved.text
    assert (
        client.post(rid + "/approve", json={"expected_version": 1}, headers=headers).status_code
        == 200
    )
    if kind in {"roles", "teams"}:
        assert client.get(path, headers=auth(issuer, user)).status_code == 200
    if kind == "access_revocation":
        assert client.get(path, headers=auth(issuer, user)).status_code == 404
    if kind in {"skills_map", "training"}:
        assert client.get(path, headers=auth(issuer, user)).status_code == 404


def test_stale_recommendation_expires_and_rejected_draft_never_grants_access(client, issuer):
    user = uuid4()
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    headers = auth(issuer)
    configure_provider(
        client, issuer, user, "roles", [{"user_id": str(user), "roles": ["developer"]}]
    )
    draft = client.post(path + "/recommendations", json={"kind": "roles"}, headers=headers).json()
    rid = path + "/recommendations/" + draft["id"]
    assert client.patch(path, json={"name": "Changed"}, headers=headers).status_code == 200
    assert (
        client.post(rid + "/approve", json={"expected_version": 1}, headers=headers).status_code
        == 409
    )
    assert client.get(rid, headers=headers).json()["status"] == "expired"
    draft2 = client.post(path + "/recommendations", json={"kind": "roles"}, headers=headers).json()
    rid2 = path + "/recommendations/" + draft2["id"]
    assert (
        client.post(rid2 + "/reject", json={"expected_version": 1}, headers=headers).status_code
        == 200
    )
    assert (
        client.post(rid2 + "/approve", json={"expected_version": 2}, headers=headers).status_code
        == 409
    )
    assert client.get(path, headers=auth(issuer, user)).status_code == 404


@pytest.mark.parametrize(
    "suggestion",
    [
        {"user_id": [], "roles": ["developer"]},
        {"user_id": {}, "roles": ["developer"]},
        {"user_id": "unknown", "roles": ["developer"]},
        {"user_id": "OWNER", "roles": ["owner"]},
    ],
)
def test_malformed_provider_output_is_sanitized_and_never_persisted(client, issuer, suggestion):
    user = uuid4()
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    configure_provider(client, issuer, user, "roles", [suggestion])
    response = client.post(path + "/recommendations", json={"kind": "roles"}, headers=auth(issuer))
    assert response.status_code == 503
    assert client.get(path + "/recommendations", headers=auth(issuer)).json()["total"] == 0
