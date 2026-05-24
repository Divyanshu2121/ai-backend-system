"""
Application Factory
────────────────────
Creates and configures the FastAPI application.
Import `app` from this module to run with uvicorn.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from app.db.redis import close_redis
from app.db.session import create_all_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle hooks."""
    setup_logging()

    # Create database tables on startup (use Alembic in production)
    if settings.environment != "production":
        await create_all_tables()

    yield  # Application runs here

    await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="""
## AI-Powered Autonomous Backend System

A self-learning data intelligence platform that:
- **Ingests** CSV, JSON, and Excel datasets automatically
- **Generates** optimized database schemas from raw data
- **Builds** REST APIs dynamically from your data
- **Analyzes** data using LLM-powered insights
- **Queries** data using natural language (no SQL needed)
- **Improves** over time via feedback loops

### Authentication
All endpoints (except `/health` and `/v1/auth/*`) require a Bearer JWT token.
Obtain one via `POST /v1/auth/login`.
        """,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    origins = ["*"] if settings.debug else [
        "https://yourdomain.com",
        "https://app.yourdomain.com",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Custom middleware (order matters — outermost runs first) ──────────────
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    # ── Exception handlers ────────────────────────────────────────────────────
    register_exception_handlers(app)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(api_router)

    return app


app = create_app()
