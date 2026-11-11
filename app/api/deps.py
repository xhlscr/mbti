"""请求级依赖：数据库会话、限流、客户端信息。"""

from __future__ import annotations

from collections import defaultdict
from time import monotonic

from fastapi import Request
from sqlmodel import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import RateLimited

__all__ = ["get_db", "rate_limit", "client_signature"]

_WINDOW_SECONDS = 3600
_hits: dict[str, list[float]] = defaultdict(list)


def rate_limit(request: Request) -> None:
    """每 IP 每小时创建会话次数上限。单进程内存实现，够用且零依赖。"""
    ip = request.client.host if request.client else "unknown"
    now = monotonic()
    cutoff = now - _WINDOW_SECONDS
    hits = [t for t in _hits[ip] if t > cutoff]
    if len(hits) >= settings.rate_limit_per_hour:
        _hits[ip] = hits
        raise RateLimited(f"每 IP 每小时最多 {settings.rate_limit_per_hour} 次")
    hits.append(now)
    _hits[ip] = hits


def client_signature(request: Request) -> str:
    ua = request.headers.get("user-agent", "")
    return ua[:200]
