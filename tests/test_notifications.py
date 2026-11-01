"""Recipient inbox and expiry regressions through the real HTTP/application/database path."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_advanced import auth, configure_provider, create


@pytest.fixture
def client(advanced_http_client):
    return advanced_http_client


def team_draft(client, issuer):
    target = uuid4()
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    configure_provider(
        client,
        issuer,
        target,
        "teams",
        [{"name": "Approved team", "user_ids": [str(target)], "roles": ["developer"]}],
    )
    response = client.post(path + "/recommendations", json={"kind": "teams"}, headers=auth(issuer))
    assert response.status_code == 201, response.text
    return path, target, response.json()


def test_team_approval_delivers_recipient_inbox_once_and_read_is_private(client, issuer):
    from projects_service.models import OutboxRecord

    path, target, draft = team_draft(client, issuer)
    foreign = uuid4()
    endpoint = path + "/recommendations/" + draft["id"] + "/approve"
    assert client.get("/notifications", headers=auth(issuer, target)).json()["total"] == 0
    assert (
        client.post(endpoint, json={"expected_version": 1}, headers=auth(issuer)).status_code == 200
    )
    assert (
        client.post(endpoint, json={"expected_version": 1}, headers=auth(issuer)).status_code == 200
    )
    inbox = client.get("/notifications?limit=1&offset=0", headers=auth(issuer, target))
    assert inbox.status_code == 200
    assert inbox.headers["cache-control"] == "no-store"
    page = inbox.json()
    assert page["total"] == 1 and page["limit"] == 1 and page["offset"] == 0
    notification = page["items"][0]
    assert set(notification) == {
        "id",
        "project_id",
        "kind",
        "title",
        "message",
        "created_at",
        "read_at",
    }
    assert notification["project_id"] == path.split("/")[-1]
    assert notification["kind"] == "team_recommendation_approved"
    assert notification["read_at"] is None
    assert client.get("/notifications", headers=auth(issuer, foreign)).json()["total"] == 0
    assert client.get("/notifications", headers=auth(issuer)).json()["total"] == 1
    mark = "/notifications/" + notification["id"] + "/read"
    unknown = "/notifications/" + str(uuid4()) + "/read"
    denied = client.post(mark, json={}, headers=auth(issuer, foreign))
    missing = client.post(unknown, json={}, headers=auth(issuer, foreign))
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()
    client.app.state.clock = lambda: datetime(2026, 11, 2, tzinfo=UTC)
    read = client.post(mark, json={}, headers=auth(issuer, target))
    assert read.status_code == 200
    assert read.json()["read_at"] == "2026-11-02T00:00:00Z"
    client.app.state.clock = lambda: datetime(2026, 11, 3, tzinfo=UTC)
    assert client.post(mark, json={}, headers=auth(issuer, target)).json() == read.json()
    assert (
        client.post(
            mark, json={"recipient_id": str(foreign)}, headers=auth(issuer, target)
        ).status_code
        == 422
    )
    assert client.get("/notifications", headers=auth(issuer, target)).json()["items"] == [
        read.json()
    ]
    assert client.get("/notifications").status_code == 401
    with Session(client.app.state.engine) as session:
        outbox = session.scalar(
            select(OutboxRecord).where(OutboxRecord.recommendation_id == UUID(draft["id"]))
        )
        assert outbox.status == "delivered_in_app"
        assert set(outbox.payload["recipient_ids"]) == {str(target), str(issuer["owner"])}


def test_notification_failure_rolls_back_team_grants_outbox_and_approval(client, issuer):
    from projects_service.models import NotificationRecord, OutboxRecord, TeamRecord

    path, target, draft = team_draft(client, issuer)
    endpoint = path + "/recommendations/" + draft["id"]

    def fail_notification(connection, cursor, statement, parameters, context, executemany):
        if "INSERT INTO MAIN.NOTIFICATIONS" in statement.upper():
            raise OperationalError(statement, parameters, Exception("synthetic write failure"))

    event.listen(client.app.state.engine, "before_cursor_execute", fail_notification)
    try:
        response = client.post(
            endpoint + "/approve", json={"expected_version": 1}, headers=auth(issuer)
        )
        assert response.status_code == 503
    finally:
        event.remove(client.app.state.engine, "before_cursor_execute", fail_notification)
    assert client.get(endpoint, headers=auth(issuer)).json()["status"] == "pending"
    assert client.get(path, headers=auth(issuer, target)).status_code == 404
    with Session(client.app.state.engine) as session:
        for model in (NotificationRecord, OutboxRecord, TeamRecord):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    assert (
        client.post(
            endpoint + "/approve", json={"expected_version": 1}, headers=auth(issuer)
        ).status_code
        == 200
    )
    assert client.get("/notifications", headers=auth(issuer, target)).json()["total"] == 1


def test_rejected_team_recommendation_has_no_notifications(client, issuer):
    path, target, draft = team_draft(client, issuer)
    endpoint = path + "/recommendations/" + draft["id"]
    assert (
        client.post(
            endpoint + "/reject", json={"expected_version": 1}, headers=auth(issuer)
        ).status_code
        == 200
    )
    assert client.get("/notifications", headers=auth(issuer, target)).json()["total"] == 0
    assert client.get("/notifications", headers=auth(issuer)).json()["total"] == 0


def test_role_recommendation_preserves_legacy_grant_expiration(client, issuer):
    from projects_service.models import MemberRecord

    client.app.state.clock = lambda: datetime(2026, 10, 30, tzinfo=UTC)
    target = uuid4()
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    with Session(client.app.state.engine) as session:
        session.add(
            MemberRecord(
                project_id=UUID(project["id"]),
                user_id=target,
                roles=["developer"],
                role_grants=[],
                expires_at=datetime(2026, 11, 1, tzinfo=UTC),
            )
        )
        session.commit()
    configure_provider(
        client, issuer, target, "roles", [{"user_id": str(target), "roles": ["product_owner"]}]
    )
    draft = client.post(
        path + "/recommendations", json={"kind": "roles"}, headers=auth(issuer)
    ).json()
    response = client.post(
        path + "/recommendations/" + draft["id"] + "/approve",
        json={"expected_version": 1},
        headers=auth(issuer),
    )
    assert response.status_code == 200, response.text
    assert client.get(path + "/access/v2", headers=auth(issuer, target)).json()["roles"] == [
        "developer",
        "product_owner",
    ]
    client.app.state.clock = lambda: datetime(2026, 11, 2, tzinfo=UTC)
    assert client.get(path + "/access/v2", headers=auth(issuer, target)).json()["roles"] == [
        "product_owner"
    ]


def test_team_recommendation_preserves_existing_link_expiry_and_denied_recipients(client, issuer):
    client.app.state.clock = lambda: datetime(2026, 10, 30, tzinfo=UTC)
    target = uuid4()
    denied = uuid4()
    project = create(client, issuer)
    path = "/projects/" + project["id"]
    headers = auth(issuer)
    team = client.post("/teams", json={"name": "Existing"}, headers=headers).json()
    for user in (target, denied):
        assert (
            client.post(
                "/teams/" + team["id"] + "/members", json={"user_id": str(user)}, headers=headers
            ).status_code
            == 201
        )
    assert (
        client.post(
            path + "/teams",
            json={
                "team_id": team["id"],
                "roles": ["developer"],
                "expires_at": "2026-11-01T00:00:00Z",
            },
            headers=headers,
        ).status_code
        == 201
    )
    assert client.delete(path + "/members/" + str(denied), headers=headers).status_code == 204
    configure_provider(
        client, issuer, target, "teams", [{"team_id": team["id"], "roles": ["developer"]}]
    )
    draft = client.post(path + "/recommendations", json={"kind": "teams"}, headers=headers).json()
    assert (
        client.post(
            path + "/recommendations/" + draft["id"] + "/approve",
            json={"expected_version": 1},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.get("/notifications", headers=auth(issuer, target)).json()["total"] == 1
    assert client.get("/notifications", headers=auth(issuer, denied)).json()["total"] == 0
    client.app.state.clock = lambda: datetime(2026, 11, 2, tzinfo=UTC)
    assert client.get(path, headers=auth(issuer, target)).status_code == 404


@pytest.mark.parametrize("release", ["suspended", "completed", "archived", "revoked"])
def test_only_active_authorized_allocations_reserve_capacity(client, issuer, release):
    target = uuid4()
    headers = auth(issuer)
    client.app.state.identity.profile = lambda token, user: {
        "user_id": str(user),
        "weekly_availability_hours": 40,
    }
    project = create(client, issuer)
    second = create(client, issuer)
    path = "/projects/" + project["id"]
    other_path = "/projects/" + second["id"]
    for base in (path, other_path):
        assert (
            client.post(
                base + "/members",
                json={"user_id": str(target), "roles": ["developer"]},
                headers=headers,
            ).status_code
            == 201
        )
    payload = {"user_id": str(target), "weekly_hours": "40"}
    assert client.put(path + "/allocations", json=payload, headers=headers).status_code == 200
    assert client.put(other_path + "/allocations", json=payload, headers=headers).status_code == 409
    if release == "revoked":
        assert client.delete(path + "/members/" + str(target), headers=headers).status_code == 204
    else:
        statuses = ["suspended"] if release == "suspended" else ["active", "completed"]
        for status in statuses:
            version = client.get(path, headers=headers).json()["version"]
            assert (
                client.post(
                    path + "/lifecycle",
                    json={"status": status, "expected_version": version},
                    headers=headers,
                ).status_code
                == 200
            )
        if release == "archived":
            version = client.get(path, headers=headers).json()["version"]
            assert (
                client.post(
                    path + "/archive", json={"expected_version": version}, headers=headers
                ).status_code
                == 200
            )
    response = client.put(other_path + "/allocations", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    assert (
        client.get("/allocations/me", headers=auth(issuer, target)).json()["total_allocated_hours"]
        == "40"
    )


@pytest.fixture(params=["sqlite", "postgresql"])
def concurrent_client(request, issuer, tmp_path):
    import os

    from fastapi.testclient import TestClient
    from sqlalchemy.engine import make_url
    from sqlalchemy.schema import DropSchema

    from projects_service.app import create_app
    from projects_service.config import Settings
    from projects_service.database import init_schema, migrate_schema

    schema = "test_notifications_" + uuid4().hex
    if request.param == "postgresql":
        url = os.environ.get("TEST_DATABASE_URL")
        if not url:
            pytest.skip("Disposable loopback PostgreSQL not configured")
        parsed = make_url(url)
        if (
            parsed.drivername != "postgresql+psycopg"
            or parsed.host not in {"localhost", "127.0.0.1", "::1"}
            or {"host", "hostaddr"} & set(parsed.query)
        ):
            pytest.fail("Notification test refuses remote PostgreSQL")
    else:
        url = f"sqlite:///{tmp_path / 'notifications.db'}"
    settings = Settings(
        database_url=url,
        database_schema=schema,
        jwks_url=issuer["settings"].jwks_url,
        auth_session_check_enabled=False,
        _env_file=None,
    )
    app = create_app(settings)
    init_schema(app.state.engine, schema)
    migrate_schema(app.state.engine, schema)
    migrate_schema(app.state.engine, schema)
    app.state.identity.active = lambda token, target: True
    app.state.identity.profile = lambda token, target: None
    app.state.backlog.items_snapshot = lambda token, project_id: []
    try:
        with TestClient(app) as http_client:
            yield http_client
    finally:
        if request.param == "postgresql":
            with app.state.engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        app.state.engine.dispose()


def test_concurrent_team_approval_and_read_deliver_once(concurrent_client, issuer):
    from concurrent.futures import ThreadPoolExecutor

    from projects_service.models import NotificationRecord, OutboxRecord

    client = concurrent_client
    path, target, draft = team_draft(client, issuer)
    endpoint = path + "/recommendations/" + draft["id"] + "/approve"

    def approve():
        return client.post(endpoint, json={"expected_version": 1}, headers=auth(issuer))

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: approve(), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    with Session(client.app.state.engine) as session:
        assert session.scalar(select(func.count()).select_from(NotificationRecord)) == 2
        assert session.scalar(select(func.count()).select_from(OutboxRecord)) == 1
    notification = client.get("/notifications", headers=auth(issuer, target)).json()["items"][0]

    def mark_read():
        return client.post(
            "/notifications/" + notification["id"] + "/read", json={}, headers=auth(issuer, target)
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        reads = list(pool.map(lambda _: mark_read(), range(2)))
    assert [response.status_code for response in reads] == [200, 200]
    assert reads[0].json()["read_at"] == reads[1].json()["read_at"]
    assert reads[0].json()["read_at"] is not None


def test_concurrent_backlog_callbacks_do_not_starve_projects_pool(concurrent_client, issuer):
    import socket
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import httpx
    import uvicorn

    from projects_service.integrations import BacklogClient

    client = concurrent_client
    project = create(client, issuer)
    barrier = threading.Barrier(2)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"

        def backlog(request):
            barrier.wait(timeout=5)
            with httpx.Client(timeout=3) as callback:
                authorization = callback.get(
                    base + "/projects/" + project["id"] + "/access/v2", headers=auth(issuer)
                )
            authorization.raise_for_status()
            return httpx.Response(
                200,
                json={
                    "project_id": project["id"],
                    "stories": 0,
                    "epics": 0,
                    "tasks": 0,
                    "history": 0,
                    "total": 0,
                },
            )

        client.app.state.backlog = BacklogClient(
            issuer["settings"], client=httpx.Client(transport=httpx.MockTransport(backlog))
        )
        server = uvicorn.Server(uvicorn.Config(client.app, log_level="critical", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started

            def summary():
                with httpx.Client(timeout=7) as outer:
                    return outer.get(
                        base + "/projects/" + project["id"] + "/summary", headers=auth(issuer)
                    )

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda _: summary(), range(2)))
            assert [response.status_code for response in responses] == [200, 200]
            assert all(response.json()["backlog_available"] is True for response in responses)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()
