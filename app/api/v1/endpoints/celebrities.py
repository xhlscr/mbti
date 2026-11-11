"""历史名人接口（阶段二使用，本阶段已可用）。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Query

from app.core.exceptions import CelebrityNotFound, InvalidType
from app.matching.celebrity import (
    ALL_TYPES,
    Celebrity,
    load_celebrities,
    match_celebrities,
)

router = APIRouter(tags=["celebrities"])


@lru_cache(maxsize=1)
def _pool() -> tuple[Celebrity, ...]:
    """进程内缓存；改 JSON 后重启生效。换数据库时只改这里。"""
    return tuple(load_celebrities())


def _summary(c: Celebrity) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "alias": c.alias,
        "type": c.type,
        "era": c.era,
        "region": c.region,
        "field": c.field,
        "traits": list(c.traits),
        "confidence": c.confidence,
        "portrait": c.portrait,
    }


@router.get("/celebrities")
def list_celebrities(
    type: str | None = Query(default=None, description="按类型过滤，例如 INTJ"),
) -> dict[str, Any]:
    pool = _pool()
    if type:
        code = type.strip().upper()
        if code not in ALL_TYPES:
            raise InvalidType(code)
        pool = tuple(c for c in pool if c.type == code)
    return {"count": len(pool), "items": [_summary(c) for c in pool]}


@router.get("/celebrities/{celebrity_id}")
def get_celebrity(celebrity_id: str) -> dict[str, Any]:
    for c in _pool():
        if c.id == celebrity_id:
            return {
                **_summary(c),
                "vector": c.vector,
                "basis": c.basis,
                "why": c.why,
                "quote": c.quote,
                "quote_source": c.quote_source,
                "note": c.note,
            }
    raise CelebrityNotFound(celebrity_id)


@router.get("/celebrity-matches")
def celebrity_matches(
    type: str = Query(..., description="四字母类型码，例如 INTJ"),
    ei: float | None = Query(default=None, ge=-1.0, le=1.0),
    sn: float | None = Query(default=None, ge=-1.0, le=1.0),
    tf: float | None = Query(default=None, ge=-1.0, le=1.0),
    jp: float | None = Query(default=None, ge=-1.0, le=1.0),
    also_limit: int = Query(default=2, ge=0, le=4),
) -> dict[str, Any]:
    code = type.strip().upper()
    if code not in ALL_TYPES:
        raise InvalidType(code)

    vector = {k: v for k, v in {"EI": ei, "SN": sn, "TF": tf, "JP": jp}.items() if v is not None}
    result = match_celebrities(vector or None, code, _pool(), also_limit=also_limit)
    result.pop("pool", None)
    return result
