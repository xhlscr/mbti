"""模型层公共工具。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def json_column() -> Any:
    """PostgreSQL JSONB 列。开发与生产同库，不做方言适配。"""
    return Column(JSONB, nullable=False)
