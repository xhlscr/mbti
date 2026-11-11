"""应用入口：装配路由、异常处理、CORS。

启动命令：
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import DomainError

logger = logging.getLogger("mbti")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) 建表；2) 首次启动播种题库。数据库不可用时只警告，不阻止进程启动。
    from app.core.database import init_db_bounded

    if await init_db_bounded():
        try:
            from sqlmodel import Session

            from app.core.database import engine
            from app.services.bank import ensure_seeded

            with Session(engine) as db:
                ensure_seeded(db)
        except Exception as exc:  # 播种失败不影响服务本身
            logger.warning("题库播种跳过：%s", exc)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="MBTI Test API",
        version="0.1.0",
        lifespan=lifespan,
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.code})

    @app.exception_handler(OperationalError)
    async def _db_unavailable(_: Request, exc: OperationalError) -> JSONResponse:
        # 数据库没起/密码错：给明确提示，而不是干巴巴的 500
        logger.error("数据库不可用：%s", str(exc).strip().splitlines()[0][:200])
        return JSONResponse(status_code=503, content={"detail": "database_unavailable"})

    app.include_router(health.router)
    app.include_router(api_router)
    return app


app = create_app()
