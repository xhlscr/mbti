"""结果页名人匹配：结算时算一次并落快照，读取时原样返回。

设计要点：
- 匹配只依赖 result 的 code + ratios 快照，不重读答题内容；
- 落库保证老分享链接稳定（名人库更新后结果不变）；
- 老结果没有快照时按需补算一次并写入；
- 任何失败都静默降级：返回 None，不影响主结果展示。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from sqlmodel import select

from app.matching.celebrity import match_celebrities
from app.models import ResultCelebrity

if TYPE_CHECKING:
    from sqlmodel import Session

    from app.models import Result

# 单个人物卡片对外字段；score 精确值不暴露，展示用 percent。
_CARD_FIELDS = (
    "id", "name", "alias", "type", "era", "region", "field",
    "traits", "why", "quote", "quote_source", "portrait",
    "basis", "confidence", "percent", "same_type", "match_notes",
)


def _pool() -> tuple[Any, ...]:
    from app.matching.celebrity import load_celebrities

    return tuple(load_celebrities())


def _card(item: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {k: item[k] for k in _CARD_FIELDS if k in item}


def _public(match: Mapping[str, Any]) -> dict[str, Any]:
    """裁成前端可用形状；反差位不展示。"""
    return {
        "type": match.get("type"),
        "primary": _card(match.get("primary")),
        "also": [_card(c) for c in (match.get("also") or []) if c],
        "spread": match.get("spread"),
        "runner_up": match.get("runner_up"),
        "notes": list(match.get("notes") or []),
    }


def build_snapshot(code: str, ratios: Mapping[str, float]) -> dict[str, Any] | None:
    """计算匹配结果。失败返回 None，绝不抛出。"""
    try:
        vector = {k: float(v) for k, v in ratios.items()}
        raw = match_celebrities(
            vector,
            code,
            _pool(),
            also_limit=2,
            include_contrast=False,   # 本期不展示反差位
        )
        return _public(raw)
    except Exception:
        return None


def ensure_snapshot(db: "Session", result: "Result") -> dict[str, Any] | None:
    """读取时确保快照存在：有就返回，没有就算一次并落库。"""
    row = db.exec(
        select(ResultCelebrity).where(ResultCelebrity.result_id == result.share_id)
    ).first()
    if row is not None:
        return dict(row.payload) if row.payload else None

    snapshot = build_snapshot(result.code, result.ratios)
    if snapshot is None:
        return None

    try:
        primary = snapshot.get("primary") or {}
        db.add(
            ResultCelebrity(
                result_id=result.share_id,
                algorithm_version="v1",
                primary_id=primary.get("id"),
                primary_score=None,   # 精确分不落库，快照里只有 percent
                payload=snapshot,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    return snapshot
