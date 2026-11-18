import asyncio
import json
import threading
import time
from datetime import UTC, datetime
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event
from test_advanced import auth, create
from test_module5_client import ARTIGO
from test_module5_client import delayed_resolver as delayed_resolver
from test_module5_client import module5_http as module5_http

from projects_service.app import create_app
from projects_service.config import Settings
from projects_service.database import init_schema

OFFICIAL_BASE = (
    "https://agente-tendencias-tecnologicas-fyd3bzerc9a2cqcu.chilecentral-01.azurewebsites.net"
)


@pytest.fixture(params=[True])
def curation_app(request, issuer, module5_http, tmp_path):
    url, state = module5_http
    settings = issuer["settings"].model_copy(
        update={
            "database_url": Settings(
                database_url=f"sqlite:///{(tmp_path / 'projects.db').as_posix()}",
                _env_file=None,
            ).database_url,
            "module5_enabled": request.param,
            "module5_base_url": url,
            "auth_api_base_url": url,
        }
    )
    app = create_app(settings)
    init_schema(app.state.engine, "projects")
    app.state.identity.active = lambda token, target: True

    def user_auth(user=None):
        headers = auth(issuer, user)
        state["owner_ids"][headers["Authorization"]] = str(user or issuer["owner"])
        return headers

    with TestClient(app) as client:
        project = create(client, issuer)
        yield client, project, user_auth, state


def endpoint(project, suffix):
    return "/projects/" + project["id"] + "/curation/" + suffix


def test_archived_project_owner_and_read_member_can_use_curation(curation_app):
    client, project, user_auth, state = curation_app
    owner_headers = user_auth()
    member = uuid4()
    project_path = "/projects/" + project["id"]
    assert (
        client.post(
            project_path + "/members",
            json={"user_id": str(member), "roles": ["developer"]},
            headers=owner_headers,
        ).status_code
        == 201
    )
    current_version = client.get(project_path, headers=owner_headers).json()["version"]
    for status in ("active", "completed"):
        transition = client.post(
            project_path + "/lifecycle",
            json={"status": status, "expected_version": current_version},
            headers=owner_headers,
        )
        assert transition.status_code == 200, transition.text
        current_version = transition.json()["version"]
    archive = client.post(
        project_path + "/archive", json={"expected_version": current_version}, headers=owner_headers
    )
    assert archive.status_code == 200
    archived = archive.json()
    member_headers = user_auth(member)
    feed = client.get(endpoint(project, "feed"), headers=member_headers)
    assert feed.status_code == 200, feed.text
    assert feed.headers["Cache-Control"] == "no-store"
    assert feed.json() == {
        "enabled": True,
        "artigos": [ARTIGO],
        "total": 1,
        "categoria": "geral",
        "fontes_consultadas": [],
        "fontes_indisponiveis": [],
        "truncated": False,
    }
    state["body"] = json.dumps(
        {"artigos": [ARTIGO], "pergunta": "Pergunta", "chat_id": 44}
    ).encode()
    query = client.post(
        endpoint(project, "queries"),
        json={"pergunta": "  Pergunta  "},
        headers={**owner_headers, "Cookie": "session=should-stay-private"},
    )
    assert query.status_code == 200, query.text
    assert query.json() == feed.json()
    assert client.get(project_path, headers=owner_headers).json() == archived
    assert state["session_requests"] == [
        member_headers["Authorization"],
        member_headers["Authorization"],
        owner_headers["Authorization"],
        owner_headers["Authorization"],
    ]
    feed_request, query_request = state["requests"]
    assert feed_request[:2] == ("GET", "/feed")
    assert "Authorization" not in feed_request[2] and "Cookie" not in feed_request[2]
    assert query_request[:2] == ("POST", "/consultas")
    assert query_request[2]["Authorization"] == owner_headers["Authorization"]
    assert "Cookie" not in query_request[2]
    assert json.loads(query_request[3]) == {"pergunta": "Pergunta"}


@pytest.mark.parametrize(
    "body",
    [
        {"pergunta": "  "},
        {"pergunta": "a" * 2001},
        {"pergunta": 1},
        {"pergunta": "x", "chat_id": 7},
    ],
)
def test_invalid_question_never_reaches_provider(curation_app, body):
    client, project, user_auth, state = curation_app
    result = client.post(endpoint(project, "queries"), headers=user_auth(), json=body)
    assert result.status_code == 422
    assert result.json() == {"detail": "Invalid project input"}
    assert state["requests"] == []


@pytest.mark.parametrize("curation_app", [False], indirect=True)
def test_disabled_api_still_checks_access_but_never_calls_provider(curation_app):
    client, project, user_auth, state = curation_app
    assert client.get(endpoint(project, "feed"), headers=user_auth(uuid4())).status_code == 404
    assert client.get(endpoint(project, "feed")).status_code == 401
    owner = user_auth()
    feed = client.get(endpoint(project, "feed"), headers=owner)
    assert feed.status_code == 200, feed.text
    assert feed.json() == {
        "enabled": False,
        "artigos": [],
        "total": 0,
        "categoria": "geral",
        "fontes_consultadas": [],
        "fontes_indisponiveis": [],
        "truncated": False,
    }
    result = client.post(endpoint(project, "queries"), headers=owner, json={"pergunta": "x"})
    assert result.status_code == 503
    assert state["requests"] == []


def test_outsider_cannot_trigger_enabled_query(curation_app):
    client, project, user_auth, state = curation_app
    result = client.post(
        endpoint(project, "queries"), headers=user_auth(uuid4()), json={"pergunta": "x"}
    )
    assert result.status_code == 404
    assert result.json() == {"detail": "Project unavailable"}
    assert state["requests"] == []


@pytest.mark.parametrize("invalidated_at", ["before", "during"])
def test_curation_requires_online_session_even_when_standard_setting_is_off(
    curation_app, invalidated_at
):
    client, project, user_auth, state = curation_app
    owner = user_auth()
    if invalidated_at == "before":
        state["session_ok"] = False
    else:
        state["on_curation"] = lambda: state.update(session_ok=False)
    result = client.get(endpoint(project, "feed"), headers=owner)
    assert result.status_code == 401
    assert result.headers["WWW-Authenticate"] == "Bearer"
    checks = 1 if invalidated_at == "before" else 2
    assert state["session_requests"] == [owner["Authorization"]] * checks
    assert len(state["requests"]) == checks - 1
    assert "artigos" not in result.json()


def test_token_expiry_during_provider_io_discards_results(curation_app, issuer, monkeypatch):
    client, project, _, state = curation_app
    now = int(time.time())
    headers = {"Authorization": "Bearer " + issuer["token"](updates={"exp": now + 60})}
    state["owner_ids"][headers["Authorization"]] = str(issuer["owner"])

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(now + 120, tz=UTC)

    state["on_curation"] = lambda: monkeypatch.setattr(jwt.api_jwt, "datetime", Later)
    result = client.post(endpoint(project, "queries"), headers=headers, json={"pergunta": "x"})
    assert result.status_code == 401
    assert "artigos" not in result.json()
    assert len(state["requests"]) == 1


def test_membership_revocation_during_provider_io_discards_results_and_releases_db(curation_app):
    client, project, user_auth, state = curation_app
    owner = user_auth()
    member = uuid4()
    project_path = "/projects/" + project["id"]
    assert (
        client.post(
            project_path + "/members",
            json={"user_id": str(member), "roles": ["developer"]},
            headers=owner,
        ).status_code
        == 201
    )
    engine = client.app.state.engine
    checkout_count = 0
    seen_counts, revocation_status = [], []

    def checkout(*_):
        nonlocal checkout_count
        checkout_count += 1

    def checkin(*_):
        nonlocal checkout_count
        checkout_count -= 1

    def revoke():
        seen_counts.append(checkout_count)
        revocation_status.append(
            client.delete(project_path + "/members/" + str(member), headers=owner).status_code
        )

    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    state["on_curation"] = revoke
    result = client.get(endpoint(project, "feed"), headers=user_auth(member))
    assert result.status_code == 404, result.text
    assert seen_counts == [0]
    assert revocation_status == [204]
    assert "artigos" not in result.json()


@pytest.mark.parametrize(
    "invalid",
    [
        OFFICIAL_BASE + "/anything",
        OFFICIAL_BASE + "?override",
        OFFICIAL_BASE + "#",
        OFFICIAL_BASE.replace("https://", "http://"),
        "https://untrusted.example",
        "http://127.0.0.1:8000@untrusted.example",
        "http://127.0.0.1",
        "http://127.0.0.1:bad",
    ],
)
def test_settings_reject_other_provider_targets(invalid):
    with pytest.raises(ValidationError, match="Module 5"):
        Settings(database_url="sqlite:///:memory:", module5_base_url=invalid, _env_file=None)


def test_settings_default_feature_off_with_fixed_provider():
    settings = Settings(database_url="sqlite:///:memory:", _env_file=None)
    assert not settings.module5_enabled
    assert settings.module5_base_url == OFFICIAL_BASE


@pytest.mark.parametrize(("code", "expected_status"), [(401, 401), (403, 403), (429, 503)])
def test_project_api_sanitizes_provider_errors(curation_app, code, expected_status):
    client, project, user_auth, state = curation_app
    state.update(code=code, body=b"synthetic upstream details")
    result = client.post(endpoint(project, "queries"), headers=user_auth(), json={"pergunta": "x"})
    assert result.status_code == expected_status
    assert "synthetic upstream details" not in result.text
    assert len(state["requests"]) == 1
    assert len(state["session_requests"]) == 2
    if expected_status == 401:
        assert result.headers["WWW-Authenticate"] == "Bearer"


def test_api_query_cancels_dns_on_shared_service_loop(curation_app, delayed_resolver, monkeypatch):
    from projects_service.module5_client import Module5Client

    client, project, user_auth, state = curation_app
    resolver_started, resolver_can_finish, resolver_finished = delayed_resolver
    shared_loop = client.portal.call(asyncio.get_running_loop)
    getaddrinfo = shared_loop.getaddrinfo
    shared_resolver_used = threading.Event()
    request_received = threading.Event()

    async def track_shared_dns(host, *args, **kwargs):
        if host in {"localhost", b"localhost"}:
            shared_resolver_used.set()
        return await getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(shared_loop, "getaddrinfo", track_shared_dns)
    state["on_curation"] = request_received.set
    base = client.app.state.settings.module5_base_url.replace("127.0.0.1", "localhost")
    client.app.state.module5 = Module5Client(base, deadline_seconds=0.35)
    result = client.post(endpoint(project, "queries"), json={"pergunta": "x"}, headers=user_auth())
    assert result.status_code == 503
    assert shared_resolver_used.is_set()
    assert resolver_started.is_set()
    assert not resolver_finished.is_set()
    resolver_can_finish.set()
    assert resolver_finished.wait(timeout=1)
    assert not request_received.wait(timeout=0.2)
    assert state["requests"] == []
