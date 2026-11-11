"""题库：bank → version → question。

版本一旦 published 就冻结，改题=新建版本，否则旧结果无法复现。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Column, Index, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel

from app.models.base import json_column


class QuestionBank(SQLModel, table=True):
    __tablename__ = "question_bank"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True, max_length=64)
    name: str = Field(max_length=64)
    # 不设外键：bank 与 version 互相引用会形成循环 FK，create_all 建不出来
    current_version_id: int | None = Field(default=None)


class BankVersion(SQLModel, table=True):
    __tablename__ = "bank_version"

    id: int | None = Field(default=None, primary_key=True)
    bank_id: int = Field(foreign_key="question_bank.id", index=True)
    version: int
    status: str = Field(default="draft", max_length=16)     # draft / published / archived
    question_count: int = Field(default=0)
    content_hash: str = Field(default="", max_length=64)
    published_at: datetime | None = None

    __table_args__ = (Index("ix_bank_version_bank_status", "bank_id", "status"),)


class Question(SQLModel, table=True):
    __tablename__ = "question"

    id: int | None = Field(default=None, primary_key=True)
    bank_version_id: int = Field(foreign_key="bank_version.id", index=True)
    code: str = Field(max_length=32)                       # ei_1
    dim: str = Field(max_length=2)                         # EI / SN / TF / JP
    type: str = Field(max_length=32)                       # likert5 / choice2
    stem: str
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    tags: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, default=list),
    )

    __table_args__ = (
        Index("ix_question_version_code", "bank_version_id", "code", unique=True),
        Index("ix_question_dim", "dim"),
    )
