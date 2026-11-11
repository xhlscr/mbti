"""答题会话与作答记录。

test_session.question_ids 是抽题快照，结算只认它，不受题库后续变更影响。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Column, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel

from app.models.base import json_column, utcnow


class TestSession(SQLModel, table=True):
    __tablename__ = "test_session"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    bank_version_id: int = Field(foreign_key="bank_version.id", index=True)
    question_ids: list[int] = Field(sa_column=Column(ARRAY(BigInteger), nullable=False))
    seed: int = Field(default=0)
    client: str | None = Field(default=None, sa_column=Column(Text))
    started_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    finished_at: datetime | None = None


class Answer(SQLModel, table=True):
    __tablename__ = "answer"

    session_id: UUID = Field(foreign_key="test_session.id", primary_key=True)
    question_id: int = Field(primary_key=True)
    value: dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    answered_at: datetime = Field(default_factory=utcnow)
