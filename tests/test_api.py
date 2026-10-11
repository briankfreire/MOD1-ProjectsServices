from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from projects_service.app import create_app
from projects_service.database import init_schema
from projects_service.security import SigningKeysUnavailable, TokenVerifier


@pytest.fixture
def client(issuer):
    app = create_app(issuer["settings"])
    init_schema(app.state.engine, "projects")
    with TestClient(app) as client:
        yield client


def bearer(issuer, owner=None):
    return {"Authorization": "Bearer " + issuer["token"](sub=owner)}


def test_http_create_list_and_private_detail(client, issuer):
    headers = bearer(issuer)
    response = client.post("/projects", json={"name": "  Projeto  "}, headers=headers)
    assert response.status_code == 201
    p = response.json()
    assert set(p) == {"id", "owner_id", "name", "description", "created_at"}
    assert p["owner_id"] == str(issuer["owner"]) and p["name"] == "Projeto"
    page = client.get("/projects", headers=headers).json()
    assert page == {"items": [p], "total": 1, "limit": 20, "offset": 0}
    assert client.get("/projects/" + p["id"], headers=headers).json() == p
    other = bearer(issuer, uuid4())
    assert client.get("/projects", headers=other).json()["total"] == 0
    hidden = client.get("/projects/" + p["id"], headers=other)
    missing = client.get("/projects/" + str(uuid4()), headers=other)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


@pytest.mark.parametrize(
    "data",
    [
        {"name": " "},
        {"name": "x" * 121},
        {"name": "A", "description": "x" * 2001},
        {"name": "A", "owner_id": str(uuid4())},
        {"name": None},
    ],
)
def test_http_draft_validation(client, issuer, data):
    assert client.post("/projects", json=data, headers=bearer(issuer)).status_code == 422


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc"])
def test_http_pagination_validation(client, issuer, query):
    assert client.get("/projects?" + query, headers=bearer(issuer)).status_code == 422


def test_no_store_and_safe_errors(client, issuer):
    for headers in ({}, {"Authorization": "Bearer secret-token"}, bearer(issuer)):
        result = client.get("/projects", headers=headers)
        assert result.headers["cache-control"] == "no-store"
        assert "secret-token" not in result.text
        if not headers or headers.get("Authorization") == "Bearer secret-token":
            assert result.status_code == 401 and result.headers["www-authenticate"] == "Bearer"
    result = client.post(
        "/projects", json={"name": {"sql": "secret-input"}}, headers=bearer(issuer)
    )
    assert result.status_code == 422 and "secret-input" not in result.text
    assert result.headers["cache-control"] == "no-store"


def test_cors(client):
    response = client.options(
        "/projects",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    denied = client.options(
        "/projects",
        headers={"Origin": "https://other.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in denied.headers


def test_health_and_database_failure_recovery(client, issuer):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    engine = client.app.state.engine

    def broken(connection, cursor, statement, parameters, context, executemany):
        raise OperationalError(statement, parameters, Exception("secret DSN SQL"))

    event.listen(engine, "before_cursor_execute", broken)
    try:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        failed = client.post("/projects", json={"name": "A"}, headers=bearer(issuer))
        assert failed.status_code == 503 and "secret" not in failed.text
    finally:
        event.remove(engine, "before_cursor_execute", broken)
    assert client.post("/projects", json={"name": "A"}, headers=bearer(issuer)).status_code == 201


def test_startup_does_not_execute_ddl(issuer):
    app = create_app(issuer["settings"])
    statements = []
    event.listen(
        app.state.engine,
        "before_cursor_execute",
        lambda c, cur, sql, p, ctx, many: statements.append(sql),
    )
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert statements == []
        assert client.get("/health/ready").status_code == 503
    assert not any("CREATE" in sql.upper() for sql in statements)


def test_unavailable_keys_deny_operation_but_not_liveness(issuer, monkeypatch):
    verifier = TokenVerifier(issuer["settings"])

    def unavailable(token):
        raise SigningKeysUnavailable()

    monkeypatch.setattr(verifier, "verify", unavailable)
    app = create_app(issuer["settings"], verifier=verifier)
    init_schema(app.state.engine, "projects")
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert (
            client.post("/projects", json={"name": "A"}, headers=bearer(issuer)).status_code == 503
        )
