from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateSchema

from projects_service.config import Settings
from projects_service.models import Base


def create_database_engine(settings: Settings) -> Engine:
    url = settings.database_url.get_secret_value()
    if url.startswith("sqlite:///"):
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            hide_parameters=True,
        )
        target = None
    else:
        engine = create_engine(
            url,
            pool_size=2,
            max_overflow=0,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
            hide_parameters=True,
        )
        target = settings.database_schema
    return engine.execution_options(schema_translate_map={"projects": target})


def init_schema(engine: Engine, schema: str) -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema, if_not_exists=True))
    Base.metadata.create_all(engine)
