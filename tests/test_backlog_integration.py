"""Opt-in contract regression with a separate Backlog checkout and real local HTTP."""

import importlib
import os
import socket
import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from projects_service.app import create_app
from projects_service.config import Settings
from projects_service.database import init_schema


def test_safe_deletion_refuses_backlog_data_and_deletes_empty_project(
    issuer, tmp_path, monkeypatch
):
    checkout = os.environ.get("BACKLOG_SERVICE_PATH")
    if not checkout:
        pytest.skip("BACKLOG_SERVICE_PATH not configured; separate Backlog checkout required")
    source = Path(checkout).resolve() / "src"
    assert (source / "backlog_service" / "app.py").is_file(), "Invalid Backlog checkout"
    # The separately packaged service derives OpenAPI version from its installed metadata.
    environment = Path(checkout).resolve() / ".venv"
    candidates = [environment / "Lib/site-packages", *environment.glob("lib/python*/site-packages")]
    for packages in candidates:
        if packages.is_dir():
            monkeypatch.syspath_prepend(str(packages))
    monkeypatch.syspath_prepend(str(source))
    backlog_app = importlib.import_module("backlog_service.app")
    backlog_config = importlib.import_module("backlog_service.config")
    backlog_database = importlib.import_module("backlog_service.database")
    backlog_models = importlib.import_module("backlog_service.models")

    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'projects.db').as_posix()}",
        jwks_url=issuer["settings"].jwks_url,
        jwt_issuer="mod1-auth-local",
        jwt_audience="engenharia-software-api",
        auth_session_check_enabled=False,
        _env_file=None,
    )
    projects = create_app(settings)
    init_schema(projects.state.engine, "projects")
    server = uvicorn.Server(uvicorn.Config(projects, log_level="critical", access_log=False))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, "Local Projects API did not become ready"
            backlog = backlog_app.create_app(
                backlog_config.Settings(
                    database_url=f"sqlite:///{(tmp_path / 'backlog.db').as_posix()}",
                    projects_api_base_url=base_url,
                    jwks_url=issuer["settings"].jwks_url,
                    jwt_issuer="mod1-auth-local",
                    jwt_audience="engenharia-software-api",
                    auth_session_check_enabled=False,
                    _env_file=None,
                )
            )
            backlog_database.init_schema(backlog.state.engine, "backlog")
            headers = {"Authorization": "Bearer " + issuer["token"]()}
            other_headers = {"Authorization": "Bearer " + issuer["token"](sub=uuid4())}
            with (
                httpx.Client(base_url=base_url, timeout=5, trust_env=False) as client,
                TestClient(backlog) as stories,
            ):
                # This two-service contract fixture uses signature-only Identity;
                # online revocation is covered by the separate three-API suite.
                def summary(token, project):
                    response = stories.get(
                        f"/projects/{project}/content-summary",
                        headers={"Authorization": "Bearer " + token},
                    )
                    assert response.status_code == 200, response.text
                    return response.json()

                projects.state.backlog.summary = summary
                created = client.post("/projects", json={"name": "Delete"}, headers=headers)
                assert created.status_code == 201
                project_id = created.json()["id"]
                kept = client.post("/projects", json={"name": "Keep"}, headers=headers)
                assert kept.status_code == 201
                kept_id = kept.json()["id"]
                path = f"/projects/{project_id}/stories"
                created_story = stories.post(
                    path, json={"title": "Retain history"}, headers=headers
                )
                assert created_story.status_code == 201
                story = created_story.json()
                story_path = path + "/" + story["id"]
                assert stories.get(path, headers=headers).json()["total"] == 1
                assert stories.get(path, headers=other_headers).status_code == 404
                assert (
                    client.delete(f"/projects/{project_id}", headers=other_headers).status_code
                    == 404
                )
                assert stories.get(story_path, headers=headers).json() == story

                refused = client.delete(f"/projects/{project_id}", headers=headers)
                assert refused.status_code == 409, refused.text
                assert client.get(f"/projects/{project_id}", headers=headers).status_code == 200
                assert (
                    stories.patch(story_path, json={"status": "done"}, headers=headers).status_code
                    == 200
                )
                # Reading a fresh registration records operational activity but
                # must not make it impossible to remove that otherwise empty project.
                assert client.get(f"/projects/{kept_id}", headers=headers).status_code == 200
                deleted = client.delete(f"/projects/{kept_id}", headers=headers)
                assert deleted.status_code == 204 and deleted.content == b""
                assert client.get(f"/projects/{kept_id}", headers=headers).status_code == 404
                empty_path = f"/projects/{kept_id}/stories"
                empty_story_path = empty_path + "/" + story["id"]
                denied = [
                    stories.get(empty_path, headers=headers),
                    stories.get(empty_story_path, headers=headers),
                    stories.post(
                        empty_path, json={"title": "Must not be created"}, headers=headers
                    ),
                    stories.patch(empty_story_path, json={"status": "done"}, headers=headers),
                ]
                for response in denied:
                    assert response.status_code == 404
                    assert response.json() == {"detail": "Project unavailable"}
                    assert response.headers["cache-control"] == "no-store"
                assert stories.get(path, headers=headers).status_code == 200
                assert client.get("/projects", headers=headers).json()["total"] == 1
                assert client.delete(f"/projects/{kept_id}", headers=headers).status_code == 404

                with Session(backlog.state.engine) as session:
                    retained = session.scalars(select(backlog_models.StoryRecord)).all()
                    assert len(retained) == 1
                    assert retained[0].id == UUID(story["id"])
                    assert retained[0].project_id == UUID(project_id)
                    assert retained[0].title == "Retain history"
                    assert retained[0].status == "done"
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), "Local Projects API did not shut down"
