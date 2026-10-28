import os
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from projects_service.config import Settings
from projects_service.database import create_database_engine, init_schema, migrate_schema
from projects_service.domain import ProjectDraft, ProjectPatch
from projects_service.repository import ProjectRepository
from projects_service.service import ProjectsService


def require_local(url):
    parsed = make_url(url)
    if (
        parsed.drivername != "postgresql+psycopg"
        or parsed.host not in ("localhost", "127.0.0.1", "::1")
        or "host" in parsed.query
        or "hostaddr" in parsed.query
    ):
        raise ValueError("Disposable integration requires explicit loopback PostgreSQL")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@remote.example/db",
        "postgresql+psycopg://u:p@localhost/db?host=remote.example",
        "postgresql+psycopg://u:p@localhost/db?hostaddr=1.2.3.4",
    ],
)
def test_postgres_guard_rejects_remote(url):
    with pytest.raises(ValueError):
        require_local(url)


def test_local_postgres_persistence_and_owner_queries():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL loopback not configured")
    require_local(url)
    schema = "test_projects_" + uuid4().hex
    settings = Settings(database_url=url, database_schema=schema, _env_file=None)
    engine = create_database_engine(settings)
    a, b = uuid4(), uuid4()
    try:
        init_schema(engine, schema)
        with Session(engine) as session:
            service = ProjectsService(ProjectRepository(session))
            p = service.create(a, ProjectDraft(name="A"))
            service.create(b, ProjectDraft(name="B"))
        engine.dispose()
        with Session(engine) as session:
            repo = ProjectRepository(session)
            page = repo.list_owned(a, limit=20, offset=0)
            assert page.total == 1 and page.items[0].id == p.id
            assert repo.get_owned(b, p.id) is None
            assert repo.delete_owned(b, p.id) is False
            assert repo.get_owned(a, p.id) == p
            assert repo.delete_owned(a, p.id) is True
        engine.dispose()
        with Session(engine) as session:
            repo = ProjectRepository(session)
            assert repo.get_owned(a, p.id) is None
            assert repo.list_owned(a, limit=20, offset=0).total == 0
            assert repo.list_owned(b, limit=20, offset=0).total == 1
            assert repo.delete_owned(a, p.id) is False
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def test_local_postgres_old_schema_migrates_twice_and_patch_search_persist():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL loopback not configured")
    require_local(url)
    schema = "test_projects_" + uuid4().hex
    settings = Settings(database_url=url, database_schema=schema, _env_file=None)
    engine = create_database_engine(settings)
    owner, other, project_id = uuid4(), uuid4(), uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}".projects ('
                    "id UUID PRIMARY KEY, owner_id UUID NOT NULL, "
                    "name VARCHAR(120) NOT NULL, description TEXT NOT NULL, "
                    "created_at TIMESTAMPTZ NOT NULL)"
                )
            )
            connection.execute(
                text(
                    f'INSERT INTO "{schema}".projects VALUES '
                    "(:id, :owner, 'Old 100%', 'Keep', '2026-10-01 12:00:00+00')"
                ),
                {"id": project_id, "owner": owner},
            )
        init_schema(engine, schema)
        assert "objective" not in {
            c["name"] for c in inspect(engine).get_columns("projects", schema=schema)
        }
        migrate_schema(engine, schema)
        migrate_schema(engine, schema)
        with Session(engine) as session:
            service = ProjectsService(ProjectRepository(session))
            original = service.get(owner, project_id)
            assert original.name == "Old 100%" and original.objective == ""
            assert service.patch(other, project_id, ProjectPatch(name="No")) is None
            updated = service.patch(owner, project_id, ProjectPatch(objective="Meta 🌱"))
            assert updated.objective == "Meta 🌱" and updated.description == "Keep"
            service.create(owner, ProjectDraft(name="Old 100_other"))
            service.create(other, ProjectDraft(name="Old 100%"))
        engine.dispose()
        with Session(engine) as session:
            service = ProjectsService(ProjectRepository(session))
            page = service.list(owner, q="  OLD 100%  ", limit=1)
            assert page.total == 1 and page.items == [updated]
            assert service.list(owner, q="100_", limit=1).total == 1
            assert service.get(owner, project_id).created_at == original.created_at
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
