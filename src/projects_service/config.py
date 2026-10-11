from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr = Field(repr=False)
    database_schema: str = Field(default="projects", pattern=r"^[a-z_][a-z0-9_]*$")
    jwt_issuer: str = Field(default="mod1-auth-local", min_length=1)
    jwt_audience: str = Field(default="engenharia-software-api", min_length=1)
    jwks_url: str = "http://127.0.0.1:8000/.well-known/jwks.json"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173"])

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            parsed = make_url(value.get_secret_value())
        except Exception:
            raise ValueError("Invalid database configuration") from None
        if parsed.drivername == "sqlite" and value.get_secret_value().startswith("sqlite:///"):
            return value
        if parsed.drivername != "postgresql+psycopg" or not parsed.host:
            raise ValueError("Use PostgreSQL/psycopg or isolated SQLite for tests")
        if "host" in parsed.query or "hostaddr" in parsed.query:
            raise ValueError("Configure database host only in the URL authority")
        if parsed.host not in LOOPBACK and (
            parsed.query.get("sslmode") != "verify-full" or not parsed.query.get("sslrootcert")
        ):
            raise ValueError(
                "Remote PostgreSQL requires verify-full and a trusted root certificate"
            )
        return value

    @field_validator("jwks_url")
    @classmethod
    def validate_jwks(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in LOOPBACK)
        ):
            raise ValueError("Configure a trusted HTTPS JWKS URL or HTTP loopback")
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS requires explicit HTTP origins without paths")
        return values
