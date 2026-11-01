from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import SQLAlchemyError

from projects_service.access_domain import AccessError
from projects_service.access_routes import router as access_router
from projects_service.collaboration_routes import router as collaboration_router
from projects_service.config import Settings
from projects_service.database import create_database_engine
from projects_service.integrations import AIClient, BacklogClient, IdentityStatusClient
from projects_service.routes import router
from projects_service.security import TokenVerifier
from projects_service.service import utc_now


def create_app(
    settings: Settings | None = None, *, verifier: TokenVerifier | None = None
) -> FastAPI:
    settings = settings or Settings()
    engine = create_database_engine(settings)
    # Backlog authorizes callbacks while an outer request can hold a project lock.
    # Keep that read traffic on a separate bounded pool, without weakening auth.
    # In-memory SQLite must share its single database/engine.
    callback_engine = (
        engine
        if settings.database_url.get_secret_value().endswith(":memory:")
        else create_database_engine(settings)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()
        if callback_engine is not engine:
            callback_engine.dispose()

    app = FastAPI(
        title="Módulo 1 — Projetos", version=version("projects-service"), lifespan=lifespan
    )
    app.state.engine = engine
    app.state.callback_engine = callback_engine
    app.state.verifier = verifier or TokenVerifier(settings)
    app.state.clock = utc_now
    app.state.settings = settings
    app.state.identity = IdentityStatusClient(settings)
    app.state.backlog = BacklogClient(settings)
    app.state.ai = AIClient(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def no_store(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if (
            request.url.path == "/projects"
            or request.url.path.startswith("/projects/")
            or request.url.path.startswith("/invitations/")
            or request.url.path.startswith("/teams")
            or request.url.path.startswith("/team-invitations/")
            or request.url.path.startswith("/allocations/")
            or request.url.path.startswith("/notifications")
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "Invalid project input"})

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(request: Request, error: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})

    @app.exception_handler(AccessError)
    async def access_error(request: Request, error: AccessError) -> JSONResponse:
        return JSONResponse(status_code=error.status, content={"detail": error.detail})

    app.include_router(router)
    app.include_router(access_router)
    app.include_router(collaboration_router)
    return app
