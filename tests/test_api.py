import json
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
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


def test_trusted_source_without_rs256_keys_returns_503(client, issuer):
    key = ec.generate_private_key(ec.SECP256R1())
    public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    public.update(kid="ec-key", alg="ES256", use="sig")
    issuer["state"]["payload"] = {"keys": [public]}
    result = client.get("/projects", headers=bearer(issuer))
    assert result.status_code == 503
    assert result.headers["cache-control"] == "no-store"


def test_delete_owned_project_removes_only_that_project(client, issuer):
    headers = bearer(issuer)
    project = client.post("/projects", json={"name": "Delete me"}, headers=headers).json()
    kept = client.post("/projects", json={"name": "Keep me"}, headers=headers).json()
    other_headers = bearer(issuer, uuid4())
    other = client.post("/projects", json={"name": "Other owner"}, headers=other_headers).json()

    response = client.delete("/projects/" + project["id"], headers=headers)

    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/projects/" + project["id"], headers=headers).status_code == 404
    assert client.get("/projects", headers=headers).json() == {
        "items": [kept],
        "total": 1,
        "limit": 20,
        "offset": 0,
    }
    assert client.get("/projects/" + other["id"], headers=other_headers).json() == other
    repeated = client.delete("/projects/" + project["id"], headers=headers)
    assert repeated.status_code == 404
    assert repeated.json() == {"detail": "Project unavailable"}
    assert repeated.headers["cache-control"] == "no-store"


def test_delete_hides_other_owners_projects_without_removing_them(client, issuer):
    headers = bearer(issuer)
    project = client.post("/projects", json={"name": "Private"}, headers=headers).json()
    other_headers = bearer(issuer, uuid4())

    hidden = client.delete("/projects/" + project["id"], headers=other_headers)
    missing = client.delete("/projects/" + str(uuid4()), headers=other_headers)

    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json() == {"detail": "Project unavailable"}
    assert client.get("/projects/" + project["id"], headers=headers).json() == project


@pytest.mark.parametrize("authentication", ["missing", "invalid", "expired", "wrong_scheme"])
def test_delete_requires_valid_bearer_without_touching_project(client, issuer, authentication):
    headers = bearer(issuer)
    project = client.post("/projects", json={"name": "Protected"}, headers=headers).json()
    rejected_headers = {
        "missing": {},
        "invalid": {"Authorization": "Bearer secret-invalid-token"},
        "expired": {"Authorization": "Bearer " + issuer["token"](updates={"iat": 1, "exp": 2})},
        "wrong_scheme": {"Authorization": "Basic secret-invalid-token"},
    }[authentication]

    response = client.delete("/projects/" + project["id"], headers=rejected_headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"
    assert "secret-invalid-token" not in response.text
    assert client.get("/projects/" + project["id"], headers=headers).json() == project


def test_delete_rejects_invalid_uuid(client, issuer):
    response = client.delete("/projects/secret-invalid-id", headers=bearer(issuer))
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid project input"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("failure_event", ["statement", "commit"])
def test_delete_database_failure_rolls_back_and_can_recover(client, issuer, failure_event):
    headers = bearer(issuer)
    project = client.post(
        "/projects", json={"name": "Preserved on failure"}, headers=headers
    ).json()
    engine = client.app.state.engine

    def broken_statement(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("DELETE"):
            raise OperationalError(statement, parameters, Exception("secret DSN SQL"))

    def broken_commit(connection):
        raise OperationalError("COMMIT", {}, Exception("secret DSN SQL"))

    name, handler = (
        ("before_cursor_execute", broken_statement)
        if failure_event == "statement"
        else ("commit", broken_commit)
    )
    event.listen(engine, name, handler)
    try:
        response = client.delete("/projects/" + project["id"], headers=headers)
        assert response.status_code == 503
        assert response.json() == {"detail": "Service temporarily unavailable"}
        assert response.headers["cache-control"] == "no-store"
    finally:
        event.remove(engine, name, handler)

    assert client.get("/projects/" + project["id"], headers=headers).json() == project
    assert client.delete("/projects/" + project["id"], headers=headers).status_code == 204
    assert client.get("/projects/" + project["id"], headers=headers).status_code == 404


def test_delete_cors_allows_configured_origin_only(client, issuer):
    path = "/projects/" + str(uuid4())
    preflight = {
        "Origin": "http://127.0.0.1:5173",
        "Access-Control-Request-Method": "DELETE",
        "Access-Control-Request-Headers": "authorization",
    }
    allowed = client.options(path, headers=preflight)
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    denied = client.options(path, headers={**preflight, "Origin": "https://other.example"})
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers

    project = client.post("/projects", json={"name": "CORS"}, headers=bearer(issuer)).json()
    response = client.delete(
        "/projects/" + project["id"],
        headers={**bearer(issuer), "Origin": "http://127.0.0.1:5173"},
    )
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_delete_unavailable_signing_keys_preserves_project(client, issuer, monkeypatch):
    headers = bearer(issuer)
    project = client.post("/projects", json={"name": "Protected"}, headers=headers).json()
    verifier = client.app.state.verifier
    with monkeypatch.context() as patch:

        def unavailable(token):
            raise SigningKeysUnavailable()

        patch.setattr(verifier, "verify", unavailable)
        response = client.delete("/projects/" + project["id"], headers=headers)
        assert response.status_code == 503
        assert response.json() == {"detail": "Service temporarily unavailable"}
    assert client.get("/projects/" + project["id"], headers=headers).json() == project


def test_delete_openapi_documents_bearer_and_empty_success(client):
    operation = client.get("/openapi.json").json()["paths"]["/projects/{project_id}"]["delete"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert "content" not in operation["responses"]["204"]
    for status in ("401", "404", "422", "503"):
        assert status in operation["responses"]
