"""抽题、作答、结算。"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from app.api.deps import (
    client_signature,
    rate_limit,
    rate_limit_answers,
    rate_limit_submit,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import (
    InvalidAnswer,
    InvalidBank,
    SessionExpired,
    SessionNotFound,
)
from app.models import Answer, Question, TestSession
from app.schemas import (
    AnswersIn,
    AnswersSavedOut,
    CreateSessionIn,
    QuestionOut,
    SessionOut,
    SessionResumeOut,
    SubmitIn,
    SubmitOut,
)
from app.services.bank import ensure_seeded, load_questions, published_version
from app.services.draw import draw
from app.services.settle import submit as settle_submit

router = APIRouter(prefix="/sessions", tags=["sessions"])

# 单次提交最多 40 题，与前端题库规模一致；schema 层也会做一次同样的上限校验。
MAX_ANSWERS = 40


def _out(q: Question) -> QuestionOut:
    return QuestionOut(
        id=q.code, dim=q.dim, type=q.type, stem=q.stem,
        options=list(q.payload.get("options", [])),
    )


def _get_session(db: Session, session_id: str) -> TestSession:
    try:
        session = db.get(TestSession, session_id)
    except Exception:                      # 非法 UUID 字符串
        session = None
    if session is None:
        raise SessionNotFound(session_id)
    return session


def _is_expired(session: TestSession) -> bool:
    expires = session.expires_at
    if expires.tzinfo is None:             # 兼容从库里取出的 naive datetime
        expires = expires.replace(tzinfo=timezone.utc)
    return expires < datetime.now(timezone.utc)


def _clean_answers(
    payload_answers: dict[str, int], questions: list[Question],
) -> dict[str, int]:
    """校验提交的答案。

    - 数量不超过本次抽题数；
    - code 必须属于当前会话的题目；
    - index 必须是合法选项下标。
    任何一条不满足都直接拒绝，避免被构造脏数据。
    """
    if len(payload_answers) > len(questions):
        raise InvalidAnswer("答案数量超过本套题数量")

    by_code = {q.code: q for q in questions}
    cleaned: dict[str, int] = {}
    for code, index in payload_answers.items():
        q = by_code.get(code)
        if q is None:
            raise InvalidAnswer(f"题目 {code} 不属于当前测试")
        options = q.payload.get("options", [])
        if not 0 <= int(index) < len(options):
            raise InvalidAnswer(f"题目 {code} 的选项下标越界")
        cleaned[code] = int(index)
    return cleaned


@router.post("", response_model=SessionOut, status_code=201,
             dependencies=[Depends(rate_limit)])
def create_session(
    payload: CreateSessionIn,
    request: Request,
    db: Session = Depends(get_db),
) -> SessionOut:
    ensure_seeded(db)
    version = published_version(db, payload.bank)
    if version is None:
        raise InvalidBank(payload.bank)

    questions = load_questions(db, version.id)
    seed = secrets.randbelow(2**31)
    picked = draw(questions, settings.per_dim, seed)

    session = TestSession(
        bank_version_id=version.id,
        question_ids=[q.id for q in picked],
        seed=seed,
        client=client_signature(request),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.session_ttl_minutes),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return SessionOut(
        session_id=str(session.id),
        bank={
            "slug": payload.bank,
            "version": version.version,
            "total": len(picked),
            "per_dim": settings.per_dim,
        },
        questions=[_out(q) for q in picked],
    )


@router.get("/{session_id}", response_model=SessionResumeOut)
def resume_session(session_id: str, db: Session = Depends(get_db)) -> SessionResumeOut:
    session = _get_session(db, session_id)
    if session.finished_at:
        raise SessionExpired("该测试已提交")
    if _is_expired(session):
        raise SessionExpired("测试已过期，请重新开始")

    questions = db.exec(select(Question).where(Question.id.in_(session.question_ids))).all()
    by_id = {q.id: q for q in questions}
    ordered = [by_id[qid] for qid in session.question_ids if qid in by_id]

    rows = db.exec(
        select(Answer).where(Answer.session_id == session.id)
    ).all()
    answers = {by_id[r.question_id].code: int(r.value.get("index", 0))
               for r in rows if r.question_id in by_id}

    return SessionResumeOut(
        session_id=str(session.id),
        bank={"slug": "mbti-v1", "version": 0, "total": len(ordered),
              "per_dim": settings.per_dim},
        questions=[_out(q) for q in ordered],
        answers=answers,
        cursor=len(answers),
        expires_at=session.expires_at.isoformat(),
    )


@router.patch("/{session_id}/answers", response_model=AnswersSavedOut,
              dependencies=[Depends(rate_limit_answers)])
def save_answers(
    session_id: str,
    payload: AnswersIn,
    db: Session = Depends(get_db),
) -> AnswersSavedOut:
    session = _get_session(db, session_id)
    if session.finished_at:
        raise SessionExpired("该测试已提交，不能再修改答案")
    if _is_expired(session):
        raise SessionExpired("测试已过期，请重新开始")

    questions = db.exec(select(Question).where(Question.id.in_(session.question_ids))).all()
    cleaned = _clean_answers(payload.answers, questions)
    by_code = {q.code: q for q in questions}

    saved = 0
    for code, index in cleaned.items():
        q = by_code[code]
        existing = db.get(Answer, (session.id, q.id))
        if existing:
            existing.value = {"index": index}
            existing.answered_at = datetime.now(timezone.utc)
            db.add(existing)
        else:
            db.add(Answer(session_id=session.id, question_id=q.id, value={"index": index}))
        saved += 1

    db.commit()
    return AnswersSavedOut(saved=saved)


@router.post("/{session_id}/submit", response_model=SubmitOut,
             dependencies=[Depends(rate_limit_submit)])
def submit(
    session_id: str,
    payload: SubmitIn,
    db: Session = Depends(get_db),
) -> SubmitOut:
    session = _get_session(db, session_id)

    # 已结算：直接返回原结果，保证幂等，也避免重复写库。
    if session.finished_at:
        result = settle_submit(db, session, payload.answers)
        return SubmitOut(
            share_id=result.share_id,
            code=result.code,
            ratios=result.ratios,
            answered=result.answered,
            total=result.total,
        )

    if _is_expired(session):
        raise SessionExpired("测试已过期，请重新开始")

    questions = db.exec(select(Question).where(Question.id.in_(session.question_ids))).all()
    cleaned = _clean_answers(payload.answers, questions)
    result = settle_submit(db, session, cleaned)
    return SubmitOut(
        share_id=result.share_id,
        code=result.code,
        ratios=result.ratios,
        answered=result.answered,
        total=result.total,
    )
