#!/usr/bin/env python3
"""清理过期的未完成测试会话，防止被刷出大量脏数据。

用法：
    python scripts/cleanup_sessions.py --days 1
    python scripts/cleanup_sessions.py --days 1 --dry-run
    python scripts/cleanup_sessions.py --purge-finished --days 180 --dry-run

- 默认只删「未完成且超过 N 天」的会话；
- 加 --purge-finished 才会删已完成的旧会话（会连带影响历史分享链接，慎用）；
- 建议挂到 cron，每天低峰跑一次。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, delete, select  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.models import Answer, Result, TestSession  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="清理过期测试会话")
    parser.add_argument("--days", type=int, default=1, help="保留最近 N 天，默认 1 天")
    parser.add_argument(
        "--purge-finished", action="store_true",
        help="同时清理已完成会话（会删除其 result，历史分享链接将失效）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只统计不删除")
    args = parser.parse_args()

    if args.days < 0:
        print("--days 不能为负数", file=sys.stderr)
        return 2

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    with Session(engine) as db:
        if args.purge_finished:
            sessions = list(db.exec(select(TestSession).where(TestSession.created_at < cutoff)))
        else:
            sessions = list(
                db.exec(
                    select(TestSession).where(
                        TestSession.finished_at.is_(None),  # type: ignore[union-attr]
                        TestSession.created_at < cutoff,
                    )
                )
            )

        session_ids = [s.id for s in sessions]
        print(f"命中会话 {len(session_ids)} 个（截止 {cutoff.isoformat()}）")
        if not session_ids:
            return 0
        if args.dry_run:
            print("dry-run：不删除")
            return 0

        # 先删子表，再删父表，避免外键冲突。
        db.exec(delete(Answer).where(Answer.session_id.in_(session_ids)))  # type: ignore[arg-type]
        if args.purge_finished:
            db.exec(delete(Result).where(Result.session_id.in_(session_ids)))  # type: ignore[arg-type]
        db.exec(delete(TestSession).where(TestSession.id.in_(session_ids)))  # type: ignore[arg-type]
        db.commit()
        print(f"已删除会话 {len(session_ids)} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
