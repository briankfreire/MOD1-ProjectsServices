from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from projects_service.module3_client import BASE_URL as MODULE3_BASE_URL
from projects_service.module3_client import trusted_base_url as trusted_artifacts_base
from projects_service.module5_client import BASE_URL, trusted_base_url

LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    module3_enabled: bool = False
    module3_base_url: str = MODULE3_BASE_URL

    @field_validator("module3_base_url")
    @classmethod
    def validate_module3_base_url(cls, value: str) -> str:
        return trusted_artifacts_base(value)

    module5_enabled: bool = False
    module5_base_url: str = BASE_URL

    @field_validator("module5_base_url")
    @classmethod
    def validate_module5_base_url(cls, value: str) -> str:
        return trusted_base_url(value)

    module6_enabled: bool = False
    module6_endpoint: str = "https://software6-bff-2-cnbqhhgdcndzgwdx.chilecentral-01.azurewebsites.net/api/integrations/notifications"
    module6_key: SecretStr | None = Field(default=None, repr=False, min_length=1, max_length=512)
    module6_source: (
        Literal[
            "code_review",
            "github",
            "curadoria",
            "artefatos",
            "rag",
            "relatorios",
            "backlog",
            "chat",
        ]
        | None
    ) = None

    @field_validator("module6_endpoint")
    @classmethod
    def validate_module6_endpoint(cls, value: str) -> str:
        from projects_service.module6_client import trusted_endpoint

        return trusted_endpoint(value)

    @model_validator(mode="after")
    def module6_configured(self) -> "Settings":
        if self.module6_enabled and (self.module6_key is None or self.module6_source is None):
            raise ValueError("Module 6 enabled requires private key and agreed source")
        if self.module6_key and any(
            ord(char) < 33 or ord(char) > 126 for char in self.module6_key.get_secret_value()
        ):
            raise ValueError("Invalid Module 6 integration key")
        return self

    database_url: SecretStr = Field(repr=False)
    database_schema: str = Field(default="projects", pattern=r"^[a-z_][a-z0-9_]*$")
    jwt_issuer: str = Field(default="mod1-auth-local", min_length=1)
    jwt_audience: str = Field(default="engenharia-software-api", min_length=1)
    jwks_url: str = "http://127.0.0.1:8000/.well-known/jwks.json"
    auth_api_base_url: str = "http://127.0.0.1:8000"
    auth_session_check_enabled: bool = True
    backlog_api_base_url: str = "http://127.0.0.1:8002"
    access_inactivity_days: int = Field(default=30, ge=1, le=3650)
    ai_base_url: str | None = None
    ai_model: str = "unconfigured"
    ai_simulated: bool = False
    ai_api_key: SecretStr | None = Field(default=None, repr=False)
    ai_provider: Literal["structured-http", "gemini"] = "structured-http"
    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_model: str = Field(
        default="gemini-3.5-flash-lite", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    gemini_timeout_seconds: int = Field(default=30, ge=1, le=30)
    gemini_max_output_tokens: int = Field(default=4096, ge=256, le=8192)
    gemini_api_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173"])

    @field_validator("gemini_api_base_url")
    @classmethod
    def validate_gemini_base(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            port = parsed.port
            trusted = (
                parsed.scheme == "https"
                and parsed.hostname == "generativelanguage.googleapis.com"
                and port in {None, 443}
            ) or (parsed.scheme == "http" and parsed.hostname in LOOPBACK)
            if (
                not trusted
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or "?" in value
                or "#" in value
                or "%" in value
                or "\\" in value
                or any(c.isspace() for c in value)
                or any(segment in {".", ".."} for segment in parsed.path.split("/"))
            ):
                raise ValueError()
        except ValueError:
            raise ValueError("Gemini requires official HTTPS or HTTP loopback") from None
        return value

    @model_validator(mode="after")
    def validate_gemini_mode(self) -> Self:
        if self.ai_provider == "gemini" and self.ai_simulated:
            raise ValueError("Gemini cannot be marked simulated")
        return self

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

    @field_validator("jwks_url", "auth_api_base_url", "backlog_api_base_url", "ai_base_url")
    @classmethod
    def validate_jwks(cls, value: str | None) -> str | None:
        if value is None:
            return value
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
