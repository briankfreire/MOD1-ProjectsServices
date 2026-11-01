"""Infrastructure probe used by the HTTP readiness endpoint."""

from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError

from projects_service.models import ProjectRecord


def database_ready(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(select(ProjectRecord.id).limit(1))
    except SQLAlchemyError:
        return False
    return True
