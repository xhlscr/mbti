"""题库版本管理：发布、查询、首次启动自动播种。

规则：一个 bank 同一时刻只有一个 published 版本；内容未变不升版。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Sequence

from sqlmodel import select

from app.core.exceptions import InvalidBank, VersionFrozen
from app.models import BankVersion, Question, QuestionBank
from app.schemas import parse_payload

if TYPE_CHECKING:
    from sqlmodel import Session

DIMS: tuple[str, ...] = ("EI", "SN", "TF", "JP")
PREFIX_DIM = {"ei": "EI", "sn": "SN", "tf": "TF", "jp": "JP"}
MIN_PER_DIM = 10
DEFAULT_WEIGHTS: tuple[int, ...] = (-2, -1, 0, 1, 2)


def build_payload(item: dict[str, Any], weights: Sequence[int] | None = None) -> dict[str, Any]:
    """把一条题（含题干字段）压成 payload。

    questions.json 把 weights 放在 bank 级别，入库时要补进每题 payload。
    """
    qtype = item.get("type", "likert5")
    if qtype == "likert5":
        return {
            "type": "likert5",
            "options": list(item.get("options") or []),
            "weights": list(item.get("weights") or weights or DEFAULT_WEIGHTS),
        }
    return {k: v for k, v in item.items() if k not in {"id", "dim", "stem", "tags"}}


def content_hash(items: Sequence[dict[str, Any]]) -> str:
    blob = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def get_or_create_bank(db: "Session", slug: str, name: str | None = None) -> QuestionBank:
    bank = db.exec(select(QuestionBank).where(QuestionBank.slug == slug)).first()
    if bank:
        return bank
    bank = QuestionBank(slug=slug, name=name or slug)
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return bank


def published_version(db: "Session", slug: str) -> BankVersion | None:
    bank = db.exec(select(QuestionBank).where(QuestionBank.slug == slug)).first()
    if not bank or not bank.current_version_id:
        return None
    return db.get(BankVersion, bank.current_version_id)


def load_questions(db: "Session", version_id: int) -> list[Question]:
    return list(
        db.exec(select(Question).where(Question.bank_version_id == version_id)).all()
    )


def validate(items: Sequence[dict[str, Any]]) -> list[str]:
    """返回全部错误，不 fail-fast，方便一次改完。"""
    errors: list[str] = []
    codes: set[str] = set()
    per_dim = dict.fromkeys(DIMS, 0)

    for item in items:
        code = str(item.get("id", ""))
        dim = item.get("dim")
        if not code:
            errors.append("存在缺少 id 的题目")
            continue
        if code in codes:
            errors.append(f"{code}: id 重复")
        codes.add(code)

        prefix = code.split("_")[0]
        if PREFIX_DIM.get(prefix) != dim:
            errors.append(f"{code}: id 前缀与 dim={dim} 不一致")
        if dim in per_dim:
            per_dim[dim] += 1

        try:
            parse_payload(build_payload(item))
        except Exception as exc:  # pydantic.ValidationError
            errors.append(f"{code}: payload 校验失败 —— {exc}".split("\n")[0])

    if len(items) < MIN_PER_DIM * len(DIMS):
        errors.append(f"题目总数 {len(items)}，至少需要 {MIN_PER_DIM * len(DIMS)} 道")
    for dim, count in per_dim.items():
        if count < MIN_PER_DIM:
            errors.append(f"{dim} 维度只有 {count} 题，至少 {MIN_PER_DIM} 道")
    return errors


def publish(
    db: "Session",
    slug: str,
    items: Sequence[dict[str, Any]],
    *,
    name: str | None = None,
    weights: Sequence[int] | None = None,
    force: bool = False,
) -> tuple[BankVersion, bool]:
    """发布新版本。返回 (版本, 是否真的有变化)。"""
    errors = validate(items)
    if errors:
        raise ValueError("题库校验失败：\n" + "\n".join(f"  - {e}" for e in errors))

    bank = get_or_create_bank(db, slug, name)
    digest = content_hash(items)
    current = published_version(db, slug)

    if current and current.content_hash == digest and not force:
        return current, False

    existing = db.exec(select(BankVersion).where(BankVersion.bank_id == bank.id)).all()
    version = BankVersion(
        bank_id=bank.id,
        version=len(existing) + 1,
        status="published",
        question_count=len(items),
        content_hash=digest,
        published_at=datetime.now(timezone.utc),
    )
    db.add(version)
    db.flush()

    for item in items:
        db.add(
            Question(
                bank_version_id=version.id,
                code=item["id"],
                dim=item["dim"],
                type=item.get("type", "likert5"),
                stem=item["stem"],
                payload=build_payload(item, weights),
                tags=list(item.get("tags") or []),
            )
        )

    # 旧版本归档
    others = db.exec(
        select(BankVersion).where(
            BankVersion.bank_id == bank.id,
            BankVersion.id != version.id,
            BankVersion.status == "published",
        )
    ).all()
    for other in others:
        other.status = "archived"

    bank.current_version_id = version.id
    db.add(bank)
    db.commit()
    db.refresh(version)
    return version, True


def ensure_seeded(db: "Session", slug: str = "mbti-v1") -> None:
    """首次启动时若无 published 版本，用 app/data/questions.json 播种一次。"""
    if published_version(db, slug):
        return
    from app.services.content_loader import question_bundle

    bundle = question_bundle()
    publish(db, slug, bundle["questions"], name="MBTI 基础题库")


def assert_writable(version: BankVersion) -> None:
    if version.status != "draft":
        raise VersionFrozen(f"版本 {version.version} 状态为 {version.status}，不可修改")
