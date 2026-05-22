"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app import __version__
from app.config import get_settings
from app.db.base import Base
from app.db.session import engine
from app.routers import admin, auth, documents, payments, recipes, subscription, trends


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables for SQLite-backed dev / test runs.
    # For Postgres production, Alembic migrations should be used instead.
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="K-Heritage Recipe AI API",
        version=__version__,
        lifespan=lifespan,
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        redoc_url="/v1/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def _http_error_handler(_: Request, exc: HTTPException):
        # Normalize the error payload shape (spec 5 common rules)
        detail = exc.detail
        if isinstance(detail, dict):
            return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "HTTP_ERROR",
                "message": str(detail),
                "status": exc.status_code,
            },
        )

    api_v1 = "/v1"
    app.include_router(auth.router, prefix=api_v1)
    app.include_router(trends.router, prefix=api_v1)
    app.include_router(documents.router, prefix=api_v1)
    app.include_router(recipes.router, prefix=api_v1)
    app.include_router(subscription.router, prefix=api_v1)
    app.include_router(payments.router, prefix=api_v1)
    app.include_router(admin.router, prefix=api_v1)

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
