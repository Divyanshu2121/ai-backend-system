from fastapi import APIRouter

from app.api.v1.endpoints import ai, auth, datasets, health

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/v1")
api_router.include_router(datasets.router, prefix="/v1")
api_router.include_router(ai.router, prefix="/v1")
