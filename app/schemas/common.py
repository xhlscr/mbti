"""公共类型。"""

from typing import Literal

from pydantic import BaseModel

Dim = Literal["EI", "SN", "TF", "JP"]


class ErrorResponse(BaseModel):
    detail: str
