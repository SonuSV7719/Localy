"""
Localy FastAPI Server Entrypoint.

Sets up logging, CORS, exception handlers, lifespans, and API routes.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from localy.core.config import get_settings
from localy.core.exceptions import LocalyError
from localy.core.logging import get_logger, setup_logging
from localy.core.dependencies import get_hardware_report, get_engine
from localy.api.router import api_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """App lifecycle events: startup and shutdown."""
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)

    logger.info("localy_server_starting", host=settings.host, port=settings.port)

    # 1. Warm up hardware detection cache
    try:
        report = get_hardware_report(settings)
        logger.info("hardware_probe_completed_on_startup", summary=report.summary)
    except Exception as e:
        logger.error("hardware_probe_failed_on_startup", error=str(e))

    # 2. Advertise the API server over mDNS so LAN client apps (e.g. the Android
    #    chat screen) can auto-discover this PC. Best-effort; never fatal.
    advertiser = None
    try:
        from localy.pooling.discovery import ServerAdvertiser

        advertiser = ServerAdvertiser(port=settings.port)
        advertiser.start()
    except Exception as e:
        logger.warning("api_server_advertise_setup_failed", error=str(e))

    yield

    # 3. Shutdown: stop advertising, then gracefully unload models
    if advertiser is not None:
        try:
            advertiser.stop()
        except Exception as e:
            logger.warning("api_server_advertise_stop_failed", error=str(e))

    logger.info("localy_server_shutting_down")
    try:
        engine = get_engine(settings)
        await engine.unload_model()
    except Exception as e:
        logger.error("failed_to_unload_model_on_shutdown", error=str(e))

    # Terminate spawned child processes so they aren't orphaned (they'd hold the
    # install folder open and block upgrades). Best-effort each.
    try:
        from localy.services.pool_service import get_pool_service

        pool = get_pool_service(settings)
        pool.unload_pooled()   # stops the pooled llama-server coordinator
        pool.stop_worker()     # stops the local rpc-server worker
    except Exception as e:
        logger.warning("pool_shutdown_cleanup_failed", error=str(e))
    try:
        from localy.network.tunnel import get_tunnel_manager

        get_tunnel_manager(settings).stop()  # stops cloudflared
    except Exception as e:
        logger.warning("tunnel_shutdown_cleanup_failed", error=str(e))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title="Localy API Server",
        description="OpenAI & Ollama compatible local LLM serving API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS configuration.
    # Starlette's CORSMiddleware matches allow_origins exactly and does NOT
    # support port globs like "http://localhost:*". The desktop app (Vite dev
    # on a variable port, and the Tauri webview) needs any localhost port, so
    # we match those with a regex and keep allow_origins for exact entries.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1|tauri\.localhost)(:\d+)?|tauri://localhost)$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware: Request ID and performance logging
    @app.middleware("http")
    async def request_middleware(request: Request, call_next: Any) -> Response:
        start_time = time.perf_counter()
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # Contextual logging logic could be extended here
        logger.info(
            "http_request_start",
            method=request.method,
            path=request.url.path,
            request_id=request_id,
            client=request.client.host if request.client else None,
        )

        response: Response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            "http_request_end",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
            request_id=request_id,
        )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(round(duration_ms, 2))
        return response

    # Global Exception Handler for custom LocalyError
    @app.exception_handler(LocalyError)
    async def localy_exception_handler(request: Request, exc: LocalyError) -> JSONResponse:
        logger.error("localy_error_occurred", code=exc.error_code, message=exc.message, details=exc.details)
        status_code = status.HTTP_400_BAD_REQUEST

        # Map specific exceptions to HTTP codes
        from localy.core.exceptions import ModelNotFoundError, NoModelLoadedError, InsufficientMemoryError, InsufficientStorageError
        if isinstance(exc, (ModelNotFoundError, NoModelLoadedError)):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, (InsufficientMemoryError, InsufficientStorageError)):
            status_code = status.HTTP_507_INSUFFICIENT_STORAGE

        return JSONResponse(
            status_code=status_code,
            content=exc.to_dict(),
        )

    # Include all API routes
    app.include_router(api_router)

    return app
