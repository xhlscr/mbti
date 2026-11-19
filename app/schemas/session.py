"""会话与作答 schema。"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import Dim
from app.schemas.question import QuestionOut

MAX_ANSWERS = 40


class CreateSessionIn(BaseModel):
    bank: str = Field(default="mbti-v1", min_length=1, max_length=64)

    @field_validator("bank")
    @classmethod
    def _safe_bank(cls, value: str) -> str:
        # 题库 slug 只需要字母、数字、短横线、下划线，挡住路径/注入类输入
        if not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("bank 只能包含字母、数字、- 和 _")
        return value


class BankMeta(BaseModel):
    slug: str
    version: int
    total: int
    per_dim: int


class SessionOut(BaseModel):
    session_id: str
    bank: BankMeta
    questions: list[QuestionOut]


class SessionResumeOut(SessionOut):
    """断点续答：在题目之外带上已答内容与游标。"""

    answers: dict[str, int] = Field(default_factory=dict)
    cursor: int = 0
    expires_at: str


class AnswerMapMixin(BaseModel):
    answers: dict[str, int] = Field(default_factory=dict)

    MAX_ANSWERS: ClassVar[int] = MAX_ANSWERS

    @field_validator("answers", mode="before")
    @classmethod
    def _check_answers(cls, value: object) -> object:
        if not isinstance(value, dict):
            raise ValueError("answers 必须是对象")
        if len(value) > MAX_ANSWERS:
            raise ValueError(f"答案数量不能超过 {MAX_ANSWERS}")
        for code, index in value.items():
            if not isinstance(code, str) or not code or len(code) > 32:
                raise ValueError("题目 code 非法")
            # bool 是 int 的子类，必须显式排除，否则 True 会被 Pydantic 转成 1。
            if isinstance(index, bool) or not isinstance(index, int):
                raise ValueError("选项下标必须是整数")
            if not 0 <= index <= 4:
                raise ValueError("选项下标必须在 0-4 之间")
        return value


class AnswersIn(AnswerMapMixin):
    pass


class AnswersSavedOut(BaseModel):
    saved: int


class SubmitIn(AnswerMapMixin):
    pass


class SubmitOut(BaseModel):
    share_id: str
    code: str
    ratios: dict[Dim, float]
    answered: int
    total: int
