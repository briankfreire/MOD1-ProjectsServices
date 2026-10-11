from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from projects_service.cli import main
from projects_service.config import Settings
from projects_service.database import create_database_engine
from projects_service.domain import ProjectDraft
from projects_service.repository import ProjectRepository
from projects_service.service import ProjectsService


@pytest.mark.parametrize(
    "overrides",
    [
        {"database_schema": "projects;DROP"},
        {"jwks_url": "http://remote.example/jwks"},
        {"jwks_url": "https://user:secret-password@example.com/jwks"},
        {
            "database_url": "postgresql+psycopg://u:secret-password@remote.example/db?sslmode=require"
        },
        {"cors_origins": ["*"]},
    ],
)
def test_rejects_unsafe_config_without_echoing_secrets(overrides):
    options = {"database_url": "sqlite:///:memory:", "_env_file": None, **overrides}
    with pytest.raises(ValidationError) as error:
        Settings(**options)
    assert "secret-password" not in str(error.value)
    assert "user:secret" not in str(error.value)


def test_settings_hide_database_url():
    settings = Settings(database_url="sqlite:///secret-filename.db", _env_file=None)
    assert "secret-filename" not in repr(settings)


def test_init_is_explicit_and_idempotent(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    settings = Settings(_env_file=None)
    engine = create_database_engine(settings)
    assert inspect(engine).get_table_names() == []
    assert main(["init"]) == 0
    with Session(engine) as session:
        p = ProjectsService(ProjectRepository(session)).create(uuid4(), ProjectDraft(name="A"))
    assert main(["init"]) == 0
    with Session(engine) as session:
        assert ProjectRepository(session).get_owned(p.owner_id, p.id).name == "A"
    engine.dispose()
    assert url not in capsys.readouterr().out


def test_cli_failure_does_not_echo_connection(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "invalid://secret-password")
    assert main(["init"]) == 1
    captured = capsys.readouterr()
    assert "secret-password" not in captured.err + captured.out


def test_cli_module_runs_init(tmp_path):
    import os
    import subprocess
    import sys

    url = f"sqlite:///{tmp_path / 'module.db'}"
    result = subprocess.run(
        [sys.executable, "-m", "projects_service.cli", "init"],
        cwd=tmp_path,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0
    engine = create_database_engine(Settings(database_url=url, _env_file=None))
    try:
        assert inspect(engine).get_table_names() == ["projects"]
    finally:
        engine.dispose()
