import argparse
import sys
from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from projects_service.config import Settings
from projects_service.database import create_database_engine, init_schema


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preparar explicitamente o schema de projetos")
    parser.add_argument("command", choices=["init"])
    parser.parse_args(argv)
    try:
        settings = Settings()
        engine = create_database_engine(settings)
        try:
            init_schema(engine, settings.database_schema)
        finally:
            engine.dispose()
        print("Schema de projetos preparado.")
        return 0
    except (ValidationError, SQLAlchemyError, ValueError, OSError):
        print(
            "Não foi possível preparar o banco. Confira a configuração administrativa.",
            file=sys.stderr,
        )
        return 1
