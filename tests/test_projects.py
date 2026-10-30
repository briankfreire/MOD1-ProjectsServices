from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from projects_service.config import Settings
from projects_service.database import create_database_engine, init_schema
from projects_service.domain import ProjectDraft
from projects_service.repository import ProjectRepository
from projects_service.service import ProjectsService


@pytest.fixture
def engine(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'projects.db'}", _env_file=None)
    engine = create_database_engine(settings)
    init_schema(engine, settings.database_schema)
    yield engine
    engine.dispose()


def test_create_assigns_owner_uuid_and_utc_time(engine):
    owner = uuid4()
    now = datetime(2026, 10, 11, 12, tzinfo=UTC)
    with Session(engine) as session:
        service = ProjectsService(ProjectRepository(session), clock=lambda: now)
        p = service.create(owner, ProjectDraft(name="  Projeto  "))
        assert p.owner_id == owner and p.name == "Projeto"
        assert isinstance(p.id, UUID) and p.id != owner and p.created_at == now


def test_defaults_and_repeated_names(engine):
    with Session(engine) as session:
        service = ProjectsService(ProjectRepository(session))
        owner = uuid4()
        first = service.create(owner, ProjectDraft(name="Repetido"))
        second = service.create(owner, ProjectDraft(name="Repetido"))
        assert first.description == "" and first.id != second.id


@pytest.mark.parametrize(
    "data",
    [
        {"name": "   "},
        {"name": "😀" * 121},
        {"name": 123},
        {"name": "Projeto", "description": "x" * 2001},
        {"name": "Projeto", "description": None},
        {"name": "Projeto", "owner_id": str(uuid4())},
        {"name": "Projeto", "extra": True},
    ],
)
def test_draft_limits_and_extra_fields(data):
    with pytest.raises(ValidationError):
        ProjectDraft.model_validate(data)


def test_draft_accepts_unicode_limits_and_newlines():
    assert ProjectDraft(name="😀" * 120, description="x" * 2000).name == "😀" * 120
    assert ProjectDraft(name="A", description="linha 1\nlinha 2").description == "linha 1\nlinha 2"


def test_owner_isolation_and_stable_pagination(engine):
    owner_a, owner_b = uuid4(), uuid4()
    ids = iter(UUID(int=n) for n in (1, 3, 2, 4))
    with Session(engine) as session:
        service = ProjectsService(
            ProjectRepository(session),
            clock=lambda: datetime(2026, 10, 11, tzinfo=UTC),
            id_factory=lambda: next(ids),
        )
        projects = [service.create(owner_a, ProjectDraft(name="A")) for _ in range(3)]
        service.create(owner_b, ProjectDraft(name="B"))
        first = service.list(owner_a, limit=2)
        second = service.list(owner_a, limit=2, offset=2)
        assert first.total == second.total == 3
        assert [p.id.int for p in first.items + second.items] == [3, 2, 1]
        assert service.get(owner_b, projects[0].id) is None
        assert service.get(owner_a, uuid4()) is None
        assert service.list(owner_b).total == 1


@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (20, -1)])
def test_invalid_pagination(engine, limit, offset):
    with Session(engine) as session, pytest.raises(ValueError):
        ProjectsService(ProjectRepository(session)).list(uuid4(), limit=limit, offset=offset)


def test_persists_after_engine_recreation(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'persist.db'}", _env_file=None)
    owner = uuid4()
    engine = create_database_engine(settings)
    init_schema(engine, settings.database_schema)
    with Session(engine) as session:
        original = ProjectsService(ProjectRepository(session)).create(owner, ProjectDraft(name="A"))
    engine.dispose()
    recreated = create_database_engine(settings)
    try:
        with Session(recreated) as session:
            reloaded = ProjectsService(ProjectRepository(session)).get(owner, original.id)
            assert reloaded == original and reloaded.created_at.tzinfo == UTC
    finally:
        recreated.dispose()


def test_deletion_persists_after_engine_recreation(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'delete.db'}", _env_file=None)
    owner, other = uuid4(), uuid4()
    engine = create_database_engine(settings)
    init_schema(engine, settings.database_schema)
    with Session(engine) as session:
        service = ProjectsService(ProjectRepository(session))
        project = service.create(owner, ProjectDraft(name="Remove"))
        kept = service.create(owner, ProjectDraft(name="Keep"))
        assert service.delete(other, project.id) is False
        assert service.get(owner, project.id) == project
        assert service.delete(owner, project.id) is True
        assert service.delete(owner, project.id) is False
    engine.dispose()

    recreated = create_database_engine(settings)
    try:
        with Session(recreated) as session:
            service = ProjectsService(ProjectRepository(session))
            assert service.get(owner, project.id) is None
            assert service.list(owner).items == [kept]
            assert service.list(owner).total == 1
    finally:
        recreated.dispose()
