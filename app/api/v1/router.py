"""v1 路由聚合。"""

from fastapi import APIRouter

from app.api.v1.endpoints import celebrities, content, results, sessions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(sessions.router)
api_router.include_router(results.router)
api_router.include_router(content.router)
api_router.include_router(celebrities.router)
