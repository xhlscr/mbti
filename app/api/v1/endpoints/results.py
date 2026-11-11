"""分享结果。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.core.database import get_db
from app.core.exceptions import ResultNotFound
from app.models import Result
from app.schemas.result import FuncStackOut, ResultOut, TypeProfileOut
from app.services.content_loader import type_profile

router = APIRouter(prefix="/results", tags=["results"])


@router.get("/{share_id}", response_model=ResultOut)
def get_result(share_id: str, db: Session = Depends(get_db)) -> ResultOut:
    result = db.exec(select(Result).where(Result.share_id == share_id)).first()
    if result is None:
        raise ResultNotFound(share_id)

    profile = type_profile(result.code)
    return ResultOut(
        share_id=result.share_id,
        code=result.code,
        ratios=result.ratios,
        answered=result.answered,
        total=result.total,
        type=TypeProfileOut(**{k: v for k, v in profile.items() if k != "functions"}),
        functions=FuncStackOut(**profile["functions"]),
    )
