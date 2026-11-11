"""数据库引擎与会话依赖。

两个刻意的设计：

1. **连接超时 3 秒**：数据库没起时快速失败，而不是让 uvicorn 卡在
   "Waiting for application startup" 上无限等待。
2. **建表带超时兜底**：init_db 失败只警告，不阻止进程启动——
   /healthz 与 /docs 仍然可用，便于排障。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

logger = logging.getLogger("mbti.db")

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False,
    connect_args={"connect_timeout": settings.db_connect_timeout},
)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个会话，请求结束自动关闭。"""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """建表（幂等）。表结构变更走 sql/migrations 下的手写脚本。"""
    import app.models  # noqa: F401  导入以注册全部表

    SQLModel.metadata.create_all(engine)


async def init_db_bounded() -> bool:
    """带超时的建表；超时或失败只记警告，不阻塞启动。

    Returns:
        True 表示建表成功，False 表示跳过（数据库不可用）。
    """
    try:
        await asyncio.wait_for(
            asyncio.to_thread(init_db),
            timeout=settings.db_init_timeout_seconds,
        )
        logger.info("数据库已就绪")
        return True
    except Exception as exc:  # 超时（TimeoutError）与连接失败都在此兜住，启动不能挂
        logger.warning(
            "数据库初始化跳过（%.0fs 超时或连接失败）：%s",
            settings.db_init_timeout_seconds,
            exc,
        )
        return False
