from sqlalchemy import Engine, create_engine, event, inspect, text
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
        # SQLite's built-in lower() only folds ASCII; match Unicode name searches in tests.
        event.listen(
            engine,
            "connect",
            lambda connection, _: connection.create_function(
                "lower",
                1,
                lambda value: value.lower() if value is not None else None,
                deterministic=True,
            ),
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


def migrate_schema(engine: Engine, schema: str) -> None:
    """Explicit, additive migration; init/startup never upgrade existing tables."""
    target = schema if engine.dialect.name == "postgresql" else None
    with engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table("projects", schema=target):
            raise ValueError("Initialize a new database before migrating")
        columns = {column["name"] for column in inspector.get_columns("projects", schema=target)}
        if "objective" in columns:
            return
        preparer = connection.dialect.identifier_preparer
        table = preparer.quote("projects")
        if target:
            table = preparer.quote_schema(target) + "." + table
        connection.execute(
            text(f"ALTER TABLE {table} ADD COLUMN objective TEXT NOT NULL DEFAULT ''")
        )
