"""题目相关 schema。

`payload` 用判别联合（discriminator="type"）校验：新题型只要加一个类并进 Union，
导入阶段就能挡住写错的 payload，不会拖到线上答题才炸。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, model_validator

from app.schemas.common import Dim


class Likert5Payload(BaseModel):
    type: Literal["likert5"] = "likert5"
    options: list[str] = Field(min_length=2, max_length=7)
    weights: list[int] = Field(min_length=2, max_length=7)

    @model_validator(mode="after")
    def _check(self) -> "Likert5Payload":
        if len(self.options) != len(self.weights):
            raise ValueError("options 与 weights 长度必须一致")
        if any(abs(w) > 2 for w in self.weights):
            raise ValueError("likert5 单项权重绝对值不得超过 2")
        return self


class Choice2Payload(BaseModel):
    type: Literal["choice2"] = "choice2"
    options: list[str] = Field(min_length=2, max_length=2)
    deltas: list[dict[Dim, float]] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def _check(self) -> "Choice2Payload":
        for delta in self.deltas:
            if any(abs(v) > 2 for v in delta.values()):
                raise ValueError("choice2 增量绝对值不得超过 2")
        return self


QuestionPayload = Annotated[Likert5Payload | Choice2Payload, Field(discriminator="type")]

_payload_adapter: TypeAdapter[QuestionPayload] = TypeAdapter(QuestionPayload)


def parse_payload(raw: dict) -> Likert5Payload | Choice2Payload:
    """按 type 解析 payload，非法时抛 pydantic.ValidationError。"""
    return _payload_adapter.validate_python(raw)


class QuestionOut(BaseModel):
    """下发给前端的题目：只有题干和选项，不含权重。"""

    id: str
    dim: Dim
    type: str
    stem: str
    options: list[str]
