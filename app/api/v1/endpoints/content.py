"""内容只读接口：题库元信息、类型文案。"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.result import FuncStackOut, TypeProfileOut
from app.services.content_loader import bank_meta, functions, type_profile

router = APIRouter(tags=["content"])


@router.get("/banks/{slug}")
def get_bank(slug: str) -> dict:
    return bank_meta(slug)


@router.get("/types/{code}")
def get_type(code: str) -> dict:
    profile = type_profile(code)
    return {"type": profile, "functions": functions()[profile["code"]]}
