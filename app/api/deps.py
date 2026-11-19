"""请求级依赖：数据库会话、限流、客户端信息。"""

from __future__ import annotations

from collections import defaultdict
from time import monotonic

from fastapi import Request
from sqlmodel import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import RateLimited

__all__ = [
    "get_db",
    "rate_limit",
    "rate_limit_answers",
    "rate_limit_submit",
    "client_signature",
]

_WINDOW_SECONDS = 3600

# 每个限流维度独立计数，避免「保存答案」把「创建会话」的额度吃掉。
_hits: dict[tuple[str, str], list[float]] = defaultdict(list)


def _check(request: Request, action: str, limit: int, label: str) -> None:
    """固定窗口计数限流。单进程内存实现，零依赖，作为 Nginx 之外的第二道防线。"""
    ip = request.client.host if request.client else "unknown"
    key = (action, ip)
    now = monotonic()
    cutoff = now - _WINDOW_SECONDS
    hits = [t for t in _hits[key] if t > cutoff]
    if len(hits) >= limit:
        _hits[key] = hits
        raise RateLimited(f"每 IP 每小时最多 {limit} 次{label}")
    hits.append(now)
    _hits[key] = hits


def rate_limit(request: Request) -> None:
    """创建会话限流。"""
    _check(request, "create", settings.rate_limit_per_hour, "创建会话")


def rate_limit_answers(request: Request) -> None:
    """保存答案限流。额度放宽，因为前端答一题就会同步一次。"""
    _check(request, "answers", settings.rate_limit_answers_per_hour, "保存答案")


def rate_limit_submit(request: Request) -> None:
    """提交结果限流。"""
    _check(request, "submit", settings.rate_limit_submit_per_hour, "提交结果")


def client_signature(request: Request) -> str:
    ua = request.headers.get("user-agent", "")
    return ua[:200]
