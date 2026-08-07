from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.api.eligibility import router as eligibility_router
from apps.api.app.api.footprint_jobs import router as footprint_jobs_router
from apps.api.app.api.health import router as health_router
from apps.api.app.api.search_jobs import router as search_jobs_router
from apps.api.app.core.clock import Clock
from apps.api.app.core.config import Settings, get_settings
from apps.api.app.core.db import build_engine, build_session_factory, create_schema
from apps.api.app.core.errors import ApiError, api_error_handler
from apps.api.app.safe_fetch.service import SafeFetchGateway
from apps.api.app.services.seed import ensure_prototype_seed


def create_app(
    *,
    settings: Settings | None = None,
    clock: Clock | None = None,
    safe_fetch_factory=None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_clock = clock or Clock()
    engine = build_engine(resolved_settings.database_url)
    session_factory = build_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        create_schema(engine)
        with session_factory() as session, session.begin():
            ensure_prototype_seed(
                session,
                resolved_settings,
                resolved_clock.now(),
            )
        yield
        engine.dispose()

    application = FastAPI(
        title="Public Profile Search Prototype",
        version="0.2.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.clock = resolved_clock
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.safe_fetch_factory = safe_fetch_factory or (
        lambda: SafeFetchGateway(resolved_settings)
    )
    application.add_exception_handler(ApiError, api_error_handler)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=[
            "Content-Type",
            "Idempotency-Key",
            "Last-Event-ID",
            "X-Prototype-Token",
            "X-Prototype-User",
            "X-Prototype-Admin-Token",
        ],
    )

    @application.middleware("http")
    async def privacy_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    application.include_router(health_router)
    application.include_router(eligibility_router)
    application.include_router(footprint_jobs_router)
    application.include_router(search_jobs_router)
    return application


app = create_app()
