"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.routes import router
from app.config import Settings, get_settings
from app.container import Container, build_container
from app.errors import AppError
from app.logging_setup import configure_logging, get_logger, request_id_var

log = get_logger("app")


def _error(status: int, code: str, message: str, hint: str | None = None, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message": message, "hint": hint, "request_id": request_id_var.get(),
        "details": details or {}}})


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ct = container or build_container(settings)
        app.state.container = ct
        await ct.db.open()
        log.info("app.started", extra={"provider": settings.llm_provider, "engine": settings.agent_engine,
                                       "ollama_model": settings.ollama_model,
                                       "anthropic_configured": settings.anthropic_configured})
        warmup = None
        if settings.ollama_warmup and settings.llm_provider == "ollama":
            from app.llm.clients import warm_up_ollama

            warmup = asyncio.create_task(warm_up_ollama(settings))  # runs in the background
        yield
        if warmup and not warmup.done():
            warmup.cancel()
        await ct.db.close()

    app = FastAPI(title="Lenny Growth Assistant API", version=__version__, lifespan=lifespan,
                  description="Grounded assistant over Lenny's Podcast transcripts.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # last-resort guard; AppErrors are handled below
            log.exception("http.unhandled")
            response = _error(500, "INTERNAL_ERROR", "Unexpected server error")
        response.headers["X-Request-ID"] = rid
        if request.url.path not in ("/health",):
            log.info("http.request", extra={"method": request.method, "path": request.url.path,
                                            "status": response.status_code,
                                            "duration_ms": int((time.perf_counter() - started) * 1000)})
        request_id_var.reset(token)
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        log.warning("http.app_error", extra={"code": exc.code, "error": exc.message})
        return _error(exc.status_code, exc.code, exc.message, exc.hint, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errs = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return _error(422, "VALIDATION_ERROR", "Request validation failed", details={"errors": errs})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return _error(exc.status_code, "HTTP_ERROR" if exc.status_code != 404 else "NOT_FOUND", str(exc.detail))

    app.include_router(router)
    return app


app = create_app()  # uvicorn app.main:app
