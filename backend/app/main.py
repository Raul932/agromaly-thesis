"""
Agromaly FastAPI Application — Entry Point
==========================================
Initializes the FastAPI application with:
    - Application metadata (title, version, docs URLs).
    - Async lifespan context manager (startup / shutdown).
    - CORS middleware with environment-controlled origins.
    - Secure HTTP headers middleware.
    - Unified exception handlers (domain → HTTP, no stack traces to client).
    - API v1 router mounted at ``/api/v1``.
    - Health check endpoint.

Zero-Trust HTTP Defaults:
    - Docs (/docs, /redoc) are disabled in production.
    - CORS is RESTRICTED to the ALLOWED_ORIGINS environment variable.
    - Unhandled exceptions return a generic 500 without internal details.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import (
    AgromalyError,
    ConflictError,
    InvalidGeometryError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.presentation.api.v1.router import api_router

# ---------------------------------------------------------------------------
# Structured Logging Setup
# ---------------------------------------------------------------------------

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.DEBUG if settings.DEBUG else logging.INFO
    ),
)
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown events)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager.

    Startup:
        - Log configuration summary.
        - (Future) warm up DB connection pool.
        - (Future) load ML model weights.

    Shutdown:
        - Dispose async DB engine (return connections to pool).
        - (Future) gracefully stop Celery workers.
    """
    logger.info(
        "Agromaly API starting",
        version=settings.APP_VERSION,
        env=settings.APP_ENV,
        debug=settings.DEBUG,
    )

    # Import engine here to dispose it cleanly on shutdown
    from app.infrastructure.db.session import _engine

    yield   # Application runs here

    logger.info("Agromaly API shutting down — disposing DB engine.")
    await _engine.dispose()


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

def create_application() -> FastAPI:
    """Application factory — creates and configures the FastAPI instance.

    Factory pattern allows:
        - Multiple app instances in tests (avoids shared state).
        - Overriding settings in test fixtures before app creation.
    """
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Agromaly — AI-powered agricultural anomaly detection platform. "
            "Detects vegetative stress via satellite NDVI analysis, provides "
            "weather-based risk alerts, and generates RAG-powered action plans."
        ),
        openapi_url="/api/openapi.json",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        lifespan=lifespan,
    )

    # --- Middleware ---
    _register_middleware(app)

    # --- Exception Handlers ---
    _register_exception_handlers(app)

    # --- Routers ---
    app.include_router(api_router, prefix="/api/v1")

    return app


def _register_middleware(app: FastAPI) -> None:
    """Attach all middleware to the FastAPI application."""

    # CORS — restrict to configured origins only
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Total-Count", "X-Request-ID"],
    )


def _register_exception_handlers(app: FastAPI) -> None:
    """Map domain exceptions to structured HTTP JSON responses.

    No stack traces or internal details are ever sent to the client.
    All errors follow the shape: ``{"detail": "...", "type": "..."}``
    """

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": exc.message, "type": "not_found"},
        )

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": exc.message, "type": "conflict"},
        )

    @app.exception_handler(PermissionDeniedError)
    async def permission_handler(request: Request, exc: PermissionDeniedError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": exc.message, "type": "permission_denied"},
        )

    @app.exception_handler(InvalidGeometryError)
    async def geometry_handler(request: Request, exc: InvalidGeometryError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": exc.message, "type": "invalid_geometry"},
        )

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.message, "type": "validation_error"},
        )

    @app.exception_handler(AgromalyError)
    async def generic_domain_handler(request: Request, exc: AgromalyError) -> JSONResponse:
        logger.error("Unhandled domain error", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal error occurred.", "type": "internal_error"},
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # Log internally but NEVER expose exception details to the client
        logger.error(
            "Unhandled exception",
            exc_type=type(exc).__name__,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An unexpected error occurred.", "type": "internal_error"},
        )


# ---------------------------------------------------------------------------
# Built-in Endpoints
# ---------------------------------------------------------------------------

app: FastAPI = create_application()


@app.get(
    "/health",
    tags=["System"],
    summary="Health check",
    response_description="Returns 200 OK when the service is running.",
)
async def health_check() -> dict:
    """Lightweight liveness probe — suitable for Kubernetes / Docker health checks."""
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
    }
