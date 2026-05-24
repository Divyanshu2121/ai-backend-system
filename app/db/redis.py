import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return a shared async Redis client, initialising it if needed."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


class CacheService:
    """High-level cache operations wrapping Redis."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self._r = redis

    async def get(self, key: str) -> Any | None:
        raw = await self._r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    async def set(
        self, key: str, value: Any, ttl: int = settings.cache_ttl_seconds
    ) -> None:
        serialized = json.dumps(value, default=str)
        await self._r.setex(key, ttl, serialized)

    async def delete(self, key: str) -> None:
        await self._r.delete(key)

    async def delete_pattern(self, pattern: str) -> int:
        keys = await self._r.keys(pattern)
        if keys:
            return await self._r.delete(*keys)
        return 0

    async def exists(self, key: str) -> bool:
        return bool(await self._r.exists(key))

    async def increment(self, key: str, ttl: int = 60) -> int:
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl)
        result = await pipe.execute()
        return result[0]
