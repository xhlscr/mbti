"""结果与类型内容 schema。"""

from pydantic import BaseModel, Field

from app.schemas.common import Dim


class FuncStackOut(BaseModel):
    dom: str
    aux: str
    tert: str
    inf: str
    note: str = ""


class TypeProfileOut(BaseModel):
    code: str
    name: str
    overview: str
    traits: list[str] = Field(default_factory=list)
    careers: list[str] = Field(default_factory=list)
    relationships: str = ""
    growth: list[str] = Field(default_factory=list)


class ResultOut(BaseModel):
    share_id: str
    code: str
    ratios: dict[Dim, float]
    answered: int
    total: int
    type: TypeProfileOut
    functions: FuncStackOut
