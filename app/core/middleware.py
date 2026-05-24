"""
Middleware
──────────
1. RequestLoggingMiddleware — structured logs every request with timing
2. RateLimitMiddleware — per-IP sliding window rate limiting via Redis
"""

import time
import uuid
from collections.abc import Callable

import structlog
from fastapi import Request, Response
from fastapi.responses import ORJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.db.redis import get_redis

logger = structlog.get_logger(__name__)

# Endpoints that bypass rate limiting
_RATE_LIMIT_EXEMPT = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})

# AI endpoints get a tighter limit
_AI_ENDPOINTS = frozenset({"/v1/ai/query", "/v1/ai/datasets"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())[:8]
        start = time.monotonic()

        # Attach request_id to structlog context so all log lines include it
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)

        logger.info(
            "HTTP request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=elapsed_ms,
            ip=request.client.host if request.client else "unknown",
        )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        if path in _RATE_LIMIT_EXEMPT:
            return await call_next(request)

        ip = (request.client.host if request.client else "0.0.0.0")
        is_ai = any(path.startswith(ep) for ep in _AI_ENDPOINTS)
        limit = settings.rate_limit_ai_per_minute if is_ai else settings.rate_limit_per_minute
        key = f"rate_limit:{'ai' if is_ai else 'api'}:{ip}"

        try:
            redis = await get_redis()
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, 60)
            results = await pipe.execute()
            count = results[0]

            if count > limit:
                return ORJSONResponse(
                    status_code=429,
                    content={
                        "success": False,
                        "error": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "message": f"Too many requests. Limit: {limit}/min",
                        },
                    },
                    headers={"Retry-After": "60"},
                )
        except Exception:
            # Never block requests because Redis is down
            pass

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        return response
