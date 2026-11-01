"""Recommendations consume authorized real backlog contracts rather than invented usage."""

import json
from uuid import uuid4

import httpx
import pytest
from test_advanced import auth, configure_provider, create

from projects_service.integrations import AIClient, BacklogClient


@pytest.fixture
def client(advanced_http_client):
    return advanced_http_client


def test_roles_context_contains_authorized_task_assignments_and_unknown_usage(client, issuer):
    user = uuid4()
    project = create(client, issuer)
    project_id = project["id"]
    item_id = str(uuid4())
    configure_provider(
        client, issuer, user, "roles", [{"user_id": str(user), "roles": ["developer"]}]
    )
    state = {"version": 1}

    def backlog(request):
        assert request.url.path == "/projects/" + project_id + "/items"
        assert request.headers["authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": item_id,
                        "project_id": project_id,
                        "kind": "task",
                        "title": "Test real assignment",
                        "status": "in_progress",
                        "assignee_id": str(user),
                        "version": state["version"],
                        "description": "Not needed in model context",
                        "created_by": str(issuer["owner"]),
                    }
                ],
                "total": 1,
                "limit": 100,
                "offset": 0,
            },
        )

    settings = issuer["settings"].model_copy(
        update={"ai_base_url": "http://127.0.0.1:9999", "ai_simulated": True}
    )
    client.app.state.backlog = BacklogClient(
        settings, client=httpx.Client(transport=httpx.MockTransport(backlog))
    )

    def provider(request):
        context = json.loads(request.content)["context"]
        assert context["work_items"][0]["id"] == item_id
        assert "description" not in context["work_items"][0]
        assert context["task_assignments"] == [
            {"item_id": item_id, "user_id": str(user), "status": "in_progress"}
        ]
        assert context["access_usage"]["status"] == "not_requested"
        assert context["backlog_snapshot_status"] == "available"
        return httpx.Response(
            200,
            json={
                "summary": "Based on task",
                "justification": "Human approval required",
                "evidence": ["item:" + item_id],
                "suggestions": [{"user_id": str(user), "roles": ["developer"]}],
            },
        )

    client.app.state.ai = AIClient(
        settings, client=httpx.Client(transport=httpx.MockTransport(provider))
    )
    path = "/projects/" + project_id
    response = client.post(path + "/recommendations", json={"kind": "roles"}, headers=auth(issuer))
    assert response.status_code == 201, response.text
    draft = response.json()
    state["version"] = 2
    approval = client.post(
        path + "/recommendations/" + draft["id"] + "/approve",
        json={"expected_version": 1},
        headers=auth(issuer),
    )
    assert approval.status_code == 409
    assert client.get(path, headers=auth(issuer, user)).status_code == 404


@pytest.mark.parametrize(
    "payload,status,expected",
    [
        ({"items": [], "total": 0, "limit": 100, "offset": 0}, 503, 503),
        ({"items": [], "total": 201, "limit": 100, "offset": 0}, 200, 422),
        ({"items": [], "total": 1, "limit": 100, "offset": 0}, 200, 503),
    ],
)
def test_unavailable_or_incomplete_backlog_does_not_become_empty_context(
    client, issuer, payload, status, expected
):
    user = uuid4()
    project = create(client, issuer)
    configure_provider(
        client, issuer, user, "roles", [{"user_id": str(user), "roles": ["developer"]}]
    )
    client.app.state.backlog = BacklogClient(
        issuer["settings"],
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload))
        ),
    )
    response = client.post(
        "/projects/" + project["id"] + "/recommendations",
        json={"kind": "roles"},
        headers=auth(issuer),
    )
    assert response.status_code == expected
    assert (
        client.get("/projects/" + project["id"] + "/recommendations", headers=auth(issuer)).json()[
            "total"
        ]
        == 0
    )


def test_backlog_summary_accepts_all_relevant_content_counters_and_rejects_unknown(issuer):
    from projects_service.access_domain import AccessError

    project_id = uuid4()
    state = {
        "project_id": str(project_id),
        "stories": 0,
        "epics": 0,
        "tasks": 0,
        "history": 0,
        "recommendations": 1,
        "recommendation_events": 1,
        "review_events": 1,
        "total": 3,
    }
    adapter = BacklogClient(
        issuer["settings"],
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=state))
        ),
    )
    assert adapter.summary("synthetic", project_id)["total"] == 3
    state["unrecognized_resources"] = 1
    state["total"] = 4
    with pytest.raises(AccessError) as error:
        adapter.summary("synthetic", project_id)
    assert error.value.status == 503
