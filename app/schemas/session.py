"""会话与作答 schema。"""

from pydantic import BaseModel, Field

from app.schemas.common import Dim
from app.schemas.question import QuestionOut


class CreateSessionIn(BaseModel):
    bank: str = "mbti-v1"


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


class AnswersIn(BaseModel):
    answers: dict[str, int] = Field(default_factory=dict)


class AnswersSavedOut(BaseModel):
    saved: int


class SubmitIn(BaseModel):
    answers: dict[str, int] = Field(default_factory=dict)


class SubmitOut(BaseModel):
    share_id: str
    code: str
    ratios: dict[Dim, float]
    answered: int
    total: int
