from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from projects_service.app import create_app
from projects_service.database import init_schema, migrate_schema

ALL = sorted(
    [
        "project:read",
        "project:update",
        "project:delete",
        "project:members:read",
        "project:members:manage",
        "backlog:read",
        "backlog:create",
        "backlog:update",
        "backlog:update_status",
    ]
)
DEV = sorted(["project:read", "project:members:read", "backlog:read", "backlog:update_status"])
PO = sorted(set(ALL) - {"project:delete", "project:members:manage"})
PM = sorted(set(ALL) - {"project:delete"})


@pytest.fixture
def client(issuer):
    app = create_app(issuer["settings"])
    init_schema(app.state.engine, "projects")
    with TestClient(app) as client:
        yield client


def headers(issuer, user=None):
    return {"Authorization": "Bearer " + issuer["token"](sub=user)}


def project(client, issuer):
    response = client.post("/projects", json={"name": "Shared 100%"}, headers=headers(issuer))
    assert response.status_code == 201
    return "/projects/" + response.json()["id"]


def invite(client, issuer, path, user, roles, **extra):
    return client.post(
        path + "/invitations",
        json={
            "user_id": str(user),
            "roles": roles,
            **extra,
        },
        headers=headers(issuer),
    )


def join(client, issuer, path, user, roles, **extra):
    invitation = invite(client, issuer, path, user, roles, **extra)
    assert invitation.status_code == 201, invitation.text
    result = client.post(
        "/invitations/accept",
        json={"code": invitation.json()["code"]},
        headers=headers(issuer, user),
    )
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize(
    "roles,permissions",
    [
        (["developer"], DEV),
        (["product_owner"], PO),
        (["project_manager"], PM),
        (["developer", "product_owner"], PO),
    ],
)
def test_role_matrix_and_dynamic_project_access(client, issuer, roles, permissions):
    path, user = project(client, issuer), uuid4()
    access = join(client, issuer, path, user, roles)
    assert access == {
        "project_id": path.split("/")[-1],
        "user_id": str(user),
        "is_owner": False,
        "roles": sorted(roles),
        "permissions": permissions,
    }
    auth = headers(issuer, user)
    assert client.get(path + "/access", headers=auth).json() == access
    assert client.get(path, headers=auth).json()["permissions"] == permissions
    page = client.get("/projects?q=100%&limit=1", headers=auth).json()
    assert page["total"] == 1 and len(page["items"]) == 1
    assert page["items"][0]["permissions"] == permissions
    assert client.patch(path, json={"name": "Edited"}, headers=auth).status_code == (
        200 if "project:update" in permissions else 403
    )
    assert client.delete(path, headers=auth).status_code == 403
    assert client.get(path + "/members", headers=auth).json()["total"] == 2
    fixed = client.get(path + "/roles", headers=auth).json()["items"]
    assert {r["key"]: r["permissions"] for r in fixed} == {
        "developer": DEV,
        "product_owner": PO,
        "project_manager": PM,
    }
    attempted = invite(client, issuer, path, uuid4(), ["developer"])
    assert attempted.status_code == 201
    response = client.post(
        path + "/invitations", json={"user_id": str(uuid4()), "roles": ["developer"]}, headers=auth
    )
    assert response.status_code == (201 if "project:members:manage" in permissions else 403)


def test_owner_permissions_and_owner_membership_protection(client, issuer):
    path = project(client, issuer)
    auth = headers(issuer)
    assert client.get(path, headers=auth).json()["permissions"] == ALL
    access = client.get(path + "/access", headers=auth).json()
    assert access["roles"] == ["owner"] and access["is_owner"] is True
    member_path = path + "/members/" + str(issuer["owner"])
    for result in (
        client.patch(member_path, json={"roles": []}, headers=auth),
        client.delete(member_path, headers=auth),
    ):
        assert result.status_code == 409
    assert invite(client, issuer, path, issuer["owner"], ["developer"]).status_code == 409
    member = client.get(path + "/members", headers=auth).json()["items"][0]
    assert member == {
        "user_id": str(issuer["owner"]),
        "roles": ["owner"],
        "expires_at": None,
        "is_owner": True,
    }


def test_revocation_zero_roles_and_old_invites_never_restore_access(client, issuer):
    path, user = project(client, issuer), uuid4()
    stale = invite(client, issuer, path, user, ["project_manager"]).json()["code"]
    join(client, issuer, path, user, ["developer"])
    member_path = path + "/members/" + str(user)
    response = client.patch(member_path, json={"roles": []}, headers=headers(issuer))
    assert response.status_code == 200 and response.json()["roles"] == []
    assert client.get(path, headers=headers(issuer, user)).status_code == 404
    assert client.get("/projects", headers=headers(issuer, user)).json()["total"] == 0
    assert invite(client, issuer, path, user, ["developer"]).status_code == 409
    assert client.delete(member_path, headers=headers(issuer)).status_code == 204
    assert client.delete(member_path, headers=headers(issuer)).status_code == 404
    denied = client.post("/invitations/accept", json={"code": stale}, headers=headers(issuer, user))
    assert denied.status_code == 404 and denied.json() == {"detail": "Invitation unavailable"}
    join(client, issuer, path, user, ["developer"])


def test_server_clock_expiry_and_preserve_clear_membership_expiry(client, issuer):
    now = datetime(2026, 10, 28, 12, tzinfo=UTC)
    client.app.state.clock = lambda: now
    path, user = project(client, issuer), uuid4()
    future = now + timedelta(hours=1)
    join(client, issuer, path, user, ["developer"], expires_at=future.isoformat())
    member_path = path + "/members/" + str(user)
    preserved = client.patch(
        member_path, json={"roles": ["product_owner"]}, headers=headers(issuer)
    )
    assert preserved.status_code == 200
    assert datetime.fromisoformat(preserved.json()["expires_at"]) == future
    now = future
    assert client.get(path + "/access", headers=headers(issuer, user)).status_code == 404
    assert client.get(path + "/members", headers=headers(issuer)).json()["total"] == 2
    cleared = client.patch(
        member_path, json={"roles": ["developer"], "expires_at": None}, headers=headers(issuer)
    )
    assert cleared.status_code == 200 and cleared.json()["expires_at"] is None
    assert client.get(path + "/access", headers=headers(issuer, user)).status_code == 200


@pytest.mark.parametrize("action", ["accept", "decline"])
def test_invitation_bound_secret_ttl_single_use_and_no_leak(client, issuer, action):
    now = datetime(2026, 10, 28, 12, tzinfo=UTC)
    client.app.state.clock = lambda: now
    path, user = project(client, issuer), uuid4()
    data = invite(client, issuer, path, user, ["developer"]).json()
    code = data["code"]
    assert len(code) >= 43
    assert datetime.fromisoformat(data["code_expires_at"]) == now + timedelta(days=7)
    with client.app.state.engine.connect() as conn:
        stored = conn.execute(text("SELECT code_hash FROM invitations")).scalar_one()
        assert stored == sha256(code.encode()).hexdigest() and stored != code
    for auth in (headers(issuer), headers(issuer, uuid4())):
        denied = client.post("/invitations/" + action, json={"code": code}, headers=auth)
        assert denied.status_code == 404 and code not in denied.text
        assert denied.headers["cache-control"] == "no-store"
    response = client.post(
        "/invitations/" + action, json={"code": code}, headers=headers(issuer, user)
    )
    assert response.status_code == (200 if action == "accept" else 204)
    if action == "decline":
        assert response.content == b""
    for other_action in ("accept", "decline"):
        assert (
            client.post(
                "/invitations/" + other_action, json={"code": code}, headers=headers(issuer, user)
            ).status_code
            == 404
        )
    late = invite(client, issuer, path, uuid4(), ["developer"]).json()
    now += timedelta(days=7)
    expired = client.post(
        "/invitations/accept", json={"code": late["code"]}, headers=headers(issuer, late["user_id"])
    )
    assert expired.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"roles": ["owner"]},
        {"roles": ["admin"]},
        {"roles": ["developer", "developer"]},
        {"roles": "developer"},
        {"roles": None},
        {"roles": ["developer"], "permissions": ALL},
        {"roles": ["developer"], "expires_at": "2020-01-01T00:00:00Z"},
        {"roles": ["developer"], "expires_at": "2030-01-01T00:00:00"},
        {"roles": ["developer"], "expires_at": 9999999999},
    ],
)
def test_rejects_membership_escalation_invalid_expiry_and_input(client, issuer, body):
    path, user = project(client, issuer), uuid4()
    join(client, issuer, path, user, ["developer"])
    result = client.patch(path + "/members/" + str(user), json=body, headers=headers(issuer))
    assert result.status_code == 422 and result.json() == {"detail": "Invalid project input"}
    result = invite(client, issuer, path, uuid4(), body.pop("roles"), **body)
    assert result.status_code == 422


def test_hidden_project_and_cross_project_isolation(client, issuer):
    path, other, user = project(client, issuer), project(client, issuer), uuid4()
    join(client, issuer, path, user, ["project_manager"])
    for suffix in ("", "/access", "/roles", "/members"):
        response = client.get(other + suffix, headers=headers(issuer, user))
        assert response.status_code == 404 and response.json() == {"detail": "Project unavailable"}
    assert invite(client, issuer, other, user, []).status_code == 422
    response = client.patch(
        path + "/members/" + str(uuid4()), json={"roles": []}, headers=headers(issuer)
    )
    assert response.status_code == 404


def test_same_person_has_independent_roles_in_two_projects(client, issuer):
    first, second, user = project(client, issuer), project(client, issuer), uuid4()
    join(client, issuer, first, user, ["developer"])
    join(client, issuer, second, user, ["product_owner"])
    first_access = client.get(first + "/access", headers=headers(issuer, user)).json()
    second_access = client.get(second + "/access", headers=headers(issuer, user)).json()
    assert first_access["roles"] == ["developer"]
    assert "backlog:update" not in first_access["permissions"]
    assert second_access["roles"] == ["product_owner"]
    assert "backlog:update" in second_access["permissions"]
    assert client.get("/projects", headers=headers(issuer, user)).json()["total"] == 2
    assert (
        client.patch(
            first + "/members/" + str(user), json={"roles": []}, headers=headers(issuer)
        ).status_code
        == 200
    )
    assert client.get(first, headers=headers(issuer, user)).status_code == 404
    assert client.get(second + "/access", headers=headers(issuer, user)).json() == second_access


def test_atomic_invitation_accept_decline_file_sqlite(issuer, tmp_path):
    settings = issuer["settings"].model_copy(update={"database_url": "unused"})
    from projects_service.config import Settings

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'race.db'}",
        jwks_url=issuer["settings"].jwks_url,
        _env_file=None,
    )
    app = create_app(settings)
    init_schema(app.state.engine, "projects")
    with TestClient(app) as client:
        path, user = project(client, issuer), uuid4()
        code = invite(client, issuer, path, user, ["developer"]).json()["code"]

        def act(action):
            return client.post(
                "/invitations/" + action, json={"code": code}, headers=headers(issuer, user)
            ).status_code

        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(act, ["accept", "decline"]))
        assert sorted(results) in ([200, 404], [204, 404])
        page = client.get(path + "/members", headers=headers(issuer)).json()
        assert page["total"] == (2 if 200 in results else 1)


def test_rbac_migration_twice_and_delete_cascades(client, issuer):
    engine = client.app.state.engine
    migrate_schema(engine, "projects")
    migrate_schema(engine, "projects")
    assert {"members", "invitations"} <= set(inspect(engine).get_table_names())
    path, user = project(client, issuer), uuid4()
    join(client, issuer, path, user, ["developer"])
    invite(client, issuer, path, uuid4(), ["developer"])
    assert client.delete(path, headers=headers(issuer)).status_code == 204
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM members")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM invitations")).scalar_one() == 0


def test_postgresql_membership_invitation_race_and_revocation(issuer):
    import os

    from sqlalchemy.schema import DropSchema
    from test_postgres import require_local

    from projects_service.config import Settings

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL loopback not configured")
    require_local(url)
    schema = "test_rbac_" + uuid4().hex
    settings = Settings(
        database_url=url,
        database_schema=schema,
        jwks_url=issuer["settings"].jwks_url,
        _env_file=None,
    )
    app = create_app(settings)
    engine = app.state.engine
    try:
        init_schema(engine, schema)
        migrate_schema(engine, schema)
        migrate_schema(engine, schema)
        with TestClient(app) as browser:
            path, user = project(browser, issuer), uuid4()
            code = invite(browser, issuer, path, user, ["developer"]).json()["code"]

            def consume(action):
                return browser.post(
                    "/invitations/" + action, json={"code": code}, headers=headers(issuer, user)
                ).status_code

            with ThreadPoolExecutor(2) as executor:
                results = list(executor.map(consume, ["accept", "decline"]))
            assert sorted(results) in ([200, 404], [204, 404])
            if 204 in results:
                join(browser, issuer, path, user, ["developer"])
            access = browser.get(path + "/access", headers=headers(issuer, user))
            assert (
                access.status_code == 200 and "backlog:update" not in access.json()["permissions"]
            )
            changed = browser.patch(
                path + "/members/" + str(user),
                json={"roles": ["developer", "product_owner"]},
                headers=headers(issuer),
            )
            assert changed.status_code == 200
            assert (
                "backlog:update"
                in browser.get(path + "/access", headers=headers(issuer, user)).json()[
                    "permissions"
                ]
            )
            assert (
                browser.delete(path + "/members/" + str(user), headers=headers(issuer)).status_code
                == 204
            )
            assert browser.get(path, headers=headers(issuer, user)).status_code == 404
            assert (
                browser.post(
                    "/invitations/accept", json={"code": code}, headers=headers(issuer, user)
                ).status_code
                == 404
            )
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
