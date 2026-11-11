#!/usr/bin/env python
"""题库入库 CLI：校验 → 生成新版本 → 发布。

用法（在仓库根目录）::

    python backend/scripts/publish_bank.py --file backend/app/data/questions.json
    python backend/scripts/publish_bank.py --file ... --dry-run
    python backend/scripts/publish_bank.py --file ... --dsn "$MBTI_DATABASE_URL" --yes
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.services.bank import content_hash, validate  # noqa: E402

DEFAULT_FILE = BACKEND / "app" / "data" / "questions.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="发布题库新版本")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--bank", default="mbti-v1")
    parser.add_argument("--dsn", default="", help="覆盖 MBTI_DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="只校验，不写库")
    parser.add_argument("--yes", action="store_true", help="跳过写库前的确认")
    args = parser.parse_args()

    bundle = json.loads(args.file.read_text(encoding="utf-8"))
    items = bundle["questions"] if isinstance(bundle, dict) else bundle
    weights = (bundle.get("bank") or {}).get("weights") if isinstance(bundle, dict) else None

    errors = validate(items)
    if errors:
        print(f"✗ 校验失败，共 {len(errors)} 处：", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"✓ 校验通过：{len(items)} 题，内容指纹 {content_hash(items)}")

    if args.dry_run:
        print("· dry-run，未写入数据库")
        return 0

    dsn = args.dsn or settings.database_url
    print(f"→ 目标数据库：{dsn.split('@')[-1]}")
    if not args.yes:
        if input("确认写入并发布？[y/N] ").strip().lower() not in {"y", "yes"}:
            print("已取消")
            return 1

    from sqlmodel import Session, create_engine

    from app.services.bank import publish

    engine = create_engine(dsn, pool_pre_ping=True)
    with Session(engine) as db:
        version, changed = publish(db, args.bank, items, weights=weights)

    if changed:
        print(f"✓ 已发布 {args.bank} v{version.version}（{version.question_count} 题）")
    else:
        print(f"· 内容未变化，沿用 v{version.version}（no-op）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
