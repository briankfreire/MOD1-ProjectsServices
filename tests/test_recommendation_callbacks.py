"""Recommendation validation must not hold a writer while callbacks record use."""

import socket
import threading
import time
from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest
import uvicorn
from test_advanced import auth, configure_provider, create
from test_notifications import concurrent_client as concurrent_client

from projects_service.access_domain import AccessError


@contextmanager
def callbacks(client, issuer, project_id):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(client.app, log_level="critical", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started

            def items(token, target):
                try:
                    with httpx.Client(timeout=0.75, trust_env=False) as http:
                        response = http.get(
                            base + f"/projects/{target}/access/v2",
                            headers={"Authorization": "Bearer " + token},
                        )
                    response.raise_for_status()
                except httpx.HTTPError:
                    raise AccessError(503, "Backlog authorization callback failed") from None
                return []

            client.app.state.backlog.items_snapshot = items
            yield
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()


@pytest.mark.parametrize("during", ["create", "approve"])
def test_recommendations_allow_authorized_activity_callback_without_sqlite_writer_deadlock(
    concurrent_client, issuer, during
):
    client = concurrent_client
    project = create(client, issuer)
    target = uuid4()
    configure_provider(
        client,
        issuer,
        target,
        "teams",
        [
            {"name": "Reviewed team", "user_ids": [str(target)], "roles": ["developer"]},
        ],
    )
    path = "/projects/" + project["id"]
    if during == "approve":
        draft = client.post(path + "/recommendations", json={"kind": "teams"}, headers=auth(issuer))
        assert draft.status_code == 201, draft.text
        rid = draft.json()["id"]
    with callbacks(client, issuer, project["id"]):
        if during == "create":
            response = client.post(
                path + "/recommendations", json={"kind": "teams"}, headers=auth(issuer)
            )
            assert response.status_code == 201, response.text
        else:
            response = client.post(
                path + "/recommendations/" + rid + "/approve",
                json={"expected_version": 1},
                headers=auth(issuer),
            )
            assert response.status_code == 200, response.text


def test_reading_an_empty_project_does_not_make_its_deletion_impossible(concurrent_client, issuer):
    client = concurrent_client
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    client.app.state.backlog.summary = lambda token, target: {"project_id": str(target), "total": 0}
    assert client.get(path, headers=auth(issuer)).status_code == 200
    assert client.delete(path, headers=auth(issuer)).status_code == 204


def test_intervening_completed_backlog_write_invalidates_recommendation(concurrent_client, issuer):
    client = concurrent_client
    project = create(client, issuer)
    target = uuid4()
    configure_provider(
        client,
        issuer,
        target,
        "teams",
        [
            {"name": "Stale team", "user_ids": [str(target)], "roles": ["developer"]},
        ],
    )
    path = "/projects/" + project["id"]
    generate = client.app.state.ai.generate

    def write_during_generation(kind, context):
        lease = client.post(
            path + "/write-leases", json={"operation_id": str(uuid4())}, headers=auth(issuer)
        )
        assert lease.status_code == 200, lease.text
        assert (
            client.delete(
                path + "/write-leases/" + lease.json()["lease_id"], headers=auth(issuer)
            ).status_code
            == 204
        )
        return generate(kind, context)

    client.app.state.ai.generate = write_during_generation
    response = client.post(path + "/recommendations", json={"kind": "teams"}, headers=auth(issuer))
    assert response.status_code == 409, response.text
    assert client.get(path + "/recommendations", headers=auth(issuer)).json()["total"] == 0
