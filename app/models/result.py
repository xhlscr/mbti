"""结算结果。session_id 唯一约束提供提交幂等。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.models.base import json_column, utcnow


class Result(SQLModel, table=True):
    __tablename__ = "result"

    id: int | None = Field(default=None, primary_key=True)
    session_id: UUID = Field(unique=True, foreign_key="test_session.id", index=True)
    share_id: str = Field(unique=True, index=True, max_length=32)

    code: str = Field(max_length=4)
    ratios: dict[str, float] = Field(default_factory=dict, sa_column=json_column())
    answered: int = Field(default=0)
    total: int = Field(default=0)

    created_at: datetime = Field(default_factory=utcnow)
