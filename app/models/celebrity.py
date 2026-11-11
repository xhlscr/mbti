"""历史人物库与匹配结果快照（阶段二使用）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index, Text
from sqlmodel import Field, SQLModel

from app.models.base import json_column, utcnow


class Celebrity(SQLModel, table=True):
    """历史人物。字段与 app/data/celebrities.json 一一对应。

    JSON 里的 `field` 在这里叫 `domain`：`field` 与 SQLModel 的 `Field` 容易混淆。
    """

    __tablename__ = "celebrity"

    id: str = Field(primary_key=True, max_length=64)
    name: str = Field(index=True, max_length=64)
    alias: str | None = Field(default=None, max_length=64)
    era: str | None = Field(default=None, max_length=64)
    region: str | None = Field(default=None, max_length=64)
    domain: str | None = Field(default=None, max_length=64, sa_column_kwargs={"name": "field"})

    type: str = Field(index=True, max_length=4)
    basis: str = Field(default="inferred", max_length=16)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    # 四维带符号向量：负=左极(E/S/T/J)，正=右极(I/N/F/P)
    vector: dict[str, float] = Field(default_factory=dict, sa_column=json_column())
    traits: list[str] = Field(default_factory=list, sa_column=json_column())

    why: str = Field(default="", sa_column=Column(Text, nullable=False))
    quote: str | None = Field(default=None, sa_column=Column(Text))
    quote_source: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, sa_column=Column(Text))

    portrait: dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    sources: list[str] = Field(default_factory=list, sa_column=json_column())

    status: str = Field(default="published", index=True, max_length=16)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    __table_args__ = (Index("ix_celebrity_type_status", "type", "status"),)


class ResultCelebrity(SQLModel, table=True):
    """名人匹配结果快照。

    不存快照的话，名人库一更新，同一个分享链接就会变成另一个人。
    """

    __tablename__ = "result_celebrity"

    id: int | None = Field(default=None, primary_key=True)
    result_id: str = Field(index=True, max_length=32)      # 对应 result.share_id
    algorithm_version: str = Field(default="v1", max_length=16)

    primary_id: str | None = Field(default=None, max_length=64)
    primary_score: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=json_column())

    created_at: datetime = Field(default_factory=utcnow)
