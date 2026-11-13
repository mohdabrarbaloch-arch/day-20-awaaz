"""FastAPI application factory and middleware wiring."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.db import init_db
from app.limiter import limiter
from app.routers import auth, transcriptions
from app.schemas import HealthOut

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on boot. Model loading is deferred to first use."""
    settings.validate_for_production()
    init_db()
    logger.info("Awaaz %s starting (env=%s)", VERSION, settings.environment)
    yield
    logger.info("Awaaz shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Awaaz",
        description=(
            "Speech to text that runs on your own machine. Upload audio, get a "
            "transcript with timestamps, export as SRT, VTT, Markdown or plain text."
        ),
        version=VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    # --- Rate limiting ----------------------------------------------------
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please slow down."},
            headers={"Retry-After": "60"},
        )

    # --- CORS -------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    # --- Security headers -------------------------------------------------
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(self), camera=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'",
        )
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    # --- Routes -----------------------------------------------------------
    app.include_router(auth.router)
    app.include_router(transcriptions.router)

    @app.get("/api/health", response_model=HealthOut, tags=["meta"])
    def health() -> HealthOut:
        """Liveness plus whether the speech model has been loaded yet."""
        from app.engine import get_transcriber

        transcriber = get_transcriber()
        return HealthOut(
            status="ok",
            engine_ready=transcriber.is_ready,
            model=transcriber.model_name,
            version=VERSION,
        )

    # --- Static UI --------------------------------------------------------
    static_dir = __import__("pathlib").Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
