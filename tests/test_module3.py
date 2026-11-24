from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_advanced import auth, create
from test_module3_client import module3_http as module3_http

from projects_service.app import create_app
from projects_service.database import init_schema
from projects_service.models import ProjectRecord


@pytest.fixture
def artifacts_app(issuer, module3_http, tmp_path):
    base, state = module3_http
    settings = issuer["settings"].model_copy(
        update={
            "database_url": issuer["settings"].database_url.__class__(
                f"sqlite:///{(tmp_path / 'artifacts.db').as_posix()}"
            ),
            "module3_enabled": True,
            "module3_base_url": base,
            "auth_api_base_url": base,
        }
    )
    app = create_app(settings)
    init_schema(app.state.engine, "projects")
    app.state.identity.active = lambda token, target: True

    def headers(user=None):
        result = auth(issuer, user)
        state["tokens"][result["Authorization"]] = str(user or issuer["owner"])
        return result

    with TestClient(app) as client:
        project = create(client, issuer)
        yield client, project, headers, state, app


def endpoint(project, suffix=""):
    return "/projects/" + project["id"] + "/artifacts" + suffix


def link(client, project, headers):
    response = client.patch(
        "/projects/" + project["id"], headers=headers, json={"module3_project_id": 7}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_explicit_link_persists_omitted_patch_preserves_and_null_unlinks(artifacts_app):
    client, project, headers, state, _ = artifacts_app
    owner = headers()
    linked = link(client, project, owner)
    assert linked["module3_project_id"] == 7
    path = "/projects/" + project["id"]
    renamed = client.patch(path, headers=owner, json={"name": "Novo nome"})
    assert renamed.json()["module3_project_id"] == 7
    assert client.get(path, headers=owner).json()["module3_project_id"] == 7
    unlinked = client.patch(path, headers=owner, json={"module3_project_id": None})
    assert unlinked.status_code == 200
    assert unlinked.json()["module3_project_id"] is None
    assert state["requests"] == []


@pytest.mark.parametrize("value", [True, 0, -1, "7", 9007199254740992])
def test_invalid_link_never_changes_project(artifacts_app, value):
    client, project, headers, _, _ = artifacts_app
    assert (
        client.patch(
            "/projects/" + project["id"], headers=headers(), json={"module3_project_id": value}
        ).status_code
        == 422
    )


def test_unlinked_project_returns_empty_without_upstream_and_outsider_cannot_read(artifacts_app):
    client, project, headers, state, _ = artifacts_app
    response = client.get(endpoint(project), headers=headers())
    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "module3_project_id": None,
        "items": [],
        "total": 0,
        "truncated": False,
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get(endpoint(project), headers=headers(uuid4())).status_code == 404
    assert client.get(endpoint(project)).status_code == 401
    assert state["requests"] == []


def test_authorized_catalog_versions_and_attachment_are_project_scoped(artifacts_app):
    client, project, headers, state, app = artifacts_app
    owner = headers()
    link(client, project, owner)
    state["on_request"] = lambda: assert_released(app)
    catalog = client.get(endpoint(project, "/catalog"), headers=owner)
    assert catalog.status_code == 200 and catalog.json()["items"][0]["id"] == 7
    result = client.get(endpoint(project) + "?artifact_type=MARKDOWN", headers=owner)
    assert result.status_code == 200 and result.json()["items"][0]["id"] == 41
    assert "file_path" not in str(result.json())
    versions = client.get(endpoint(project, "/41/versions?module3_project_id=7"), headers=owner)
    assert versions.status_code == 200 and versions.json()["items"][0]["id"] == 81
    download = client.get(endpoint(project, "/41/download?module3_project_id=7"), headers=owner)
    assert download.status_code == 200 and download.content == b"# Requisitos\n"
    assert download.headers["Content-Disposition"] == 'attachment; filename="artifact-41.md"'
    assert download.headers["X-Content-Type-Options"] == "nosniff"
    assert download.headers["Cache-Control"] == "no-store"


def assert_released(app):
    assert app.state.engine.pool.checkedout() == 0


def test_wrong_link_and_foreign_artifact_do_not_download(artifacts_app):
    client, project, headers, state, _ = artifacts_app
    owner = headers()
    link(client, project, owner)
    assert (
        client.get(
            endpoint(project, "/41/download?module3_project_id=8"), headers=owner
        ).status_code
        == 409
    )
    assert state["requests"] == []
    assert (
        client.get(
            endpoint(project, "/999/download?module3_project_id=7"), headers=owner
        ).status_code
        == 404
    )
    assert not any("/999/download" in path for _, path, _ in state["requests"])


def test_online_session_revocation_during_upstream_discards_payload(artifacts_app):
    client, project, headers, state, _ = artifacts_app
    owner = headers()
    link(client, project, owner)
    state["on_request"] = lambda: state.update(session_ok=False)
    response = client.get(endpoint(project), headers=owner)
    assert response.status_code == 401
    assert "Requisitos" not in response.text


def test_link_change_during_io_discards_payload(artifacts_app):
    client, project, headers, state, app = artifacts_app
    owner = headers()
    link(client, project, owner)

    def change_link():
        with Session(app.state.engine) as session:
            from uuid import UUID

            row = session.get(ProjectRecord, UUID(project["id"]))
            row.details = {**row.details, "module3_project_id": 8}
            session.commit()

    state["on_request"] = change_link
    response = client.get(endpoint(project), headers=owner)
    assert response.status_code == 409
    assert "Requisitos" not in response.text
