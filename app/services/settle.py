"""结算：纯函数算分 + 落库事务。

`compute()` 不依赖 ORM，可单测；`submit()` 才是带数据库的那一半。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Mapping, Sequence

from app.core.exceptions import SessionExpired
from app.services.scoring import aggregate

if TYPE_CHECKING:
    from sqlmodel import Session

    from app.models import Result, TestSession
    from app.models.question import Question


@dataclass(frozen=True)
class Computed:
    code: str
    ratios: dict[str, float]
    answered: int
    total: int


def new_share_id() -> str:
    # URL 安全，约 8 字符，够 32^8 的空间，不需要再查重
    return secrets.token_urlsafe(6)


def compute(answers: Mapping[str, int], questions: Sequence["Question"]) -> Computed:
    """按题目 code 提交的答案 → 类型码与四维比率。

    未提交、或 code 不属于本套题的答案一律忽略；分母只累计实际作答的题目。
    """
    by_code = {q.code: q for q in questions}
    question_map: dict[object, "Question"] = {}
    for q in questions:
        question_map[q.id if q.id is not None else q.code] = q

    mapped: dict[object, dict] = {}
    for code, index in answers.items():
        q = by_code.get(code)
        if q is None:
            continue
        key = q.id if q.id is not None else q.code
        mapped[key] = {"index": int(index)}

    code, ratios = aggregate(mapped, question_map)
    return Computed(code=code, ratios=ratios, answered=len(mapped), total=len(questions))


def _is_expired(session: "TestSession") -> bool:
    expires = session.expires_at
    if expires.tzinfo is None:            # 兼容从库里取出的 naive datetime
        expires = expires.replace(tzinfo=timezone.utc)
    return expires < datetime.now(timezone.utc)


def submit(db: "Session", session: "TestSession", answers: Mapping[str, int]) -> "Result":
    """幂等结算：已结算的会话直接返回已有结果。"""
    from sqlmodel import select

    from app.models import Result
    from app.models.question import Question

    if session.finished_at:
        existing = db.exec(select(Result).where(Result.session_id == session.id)).first()
        if existing:
            return existing

    if _is_expired(session):
        raise SessionExpired()

    questions = db.exec(
        select(Question).where(Question.id.in_(session.question_ids))
    ).all()
    computed = compute(answers, questions)

    result = Result(
        session_id=session.id,
        share_id=new_share_id(),
        code=computed.code,
        ratios=computed.ratios,
        answered=computed.answered,
        total=computed.total,
    )
    session.finished_at = datetime.now(timezone.utc)
    db.add(result)
    db.add(session)
    db.commit()
    db.refresh(result)
    return result
