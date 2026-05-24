from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.db.redis import get_redis
from app.schemas.schemas import HealthResponse

router = APIRouter(tags=["Monitoring"])


@router.get("/health", response_model=HealthResponse, summary="System health check")
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    # Check database
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    # Check Redis
    redis_status = "ok"
    try:
        redis = await get_redis()
        await redis.ping()
    except Exception:
        redis_status = "error"

    return HealthResponse(
        status="healthy" if db_status == "ok" else "degraded",
        version=settings.app_version,
        environment=settings.environment,
        database=db_status,
        redis=redis_status,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/", summary="API root — redirect to docs")
async def root() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }
