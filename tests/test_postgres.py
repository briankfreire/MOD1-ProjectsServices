import os
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import DropSchema

from projects_service.config import Settings
from projects_service.database import create_database_engine, init_schema
from projects_service.domain import ProjectDraft
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
