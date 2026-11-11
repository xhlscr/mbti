#!/usr/bin/env python
"""由 `app/data/*.json` 生成可独立执行的 PostgreSQL 脚本。

    python backend/scripts/export_seed_sql.py

产物（backend/sql/）：
    01_schema.sql   建表 + 索引（幂等）
    02_seed.sql     题库 + 名人数据（幂等，可重复执行）
    03_verify.sql   导入后自检查询

设计要点：
1. 文本一律用 dollar-quoting（$s$...$s$），中文、引号、换行都不需要转义；
2. 显式指定主键 id，便于复现，末尾用 setval 把序列推到最大值；
3. 全部 INSERT 带 ON CONFLICT DO NOTHING，重复执行不会报错也不会翻倍。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DATA = BACKEND / "app" / "data"
SQL_DIR = BACKEND / "sql"

DIMS = ("EI", "SN", "TF", "JP")


# ---------------------------------------------------------------------------
# 转义与序列化
# ---------------------------------------------------------------------------


def q(text: str, tag: str = "s") -> str:
    """dollar-quoted 字符串，内容里不能出现该 tag 的结束符。"""
    marker = f"${tag}$"
    if marker in text:
        raise ValueError(f"文本包含定界符 {marker}，需要换 tag：{text[:40]}")
    return f"{marker}{text}{marker}"


def jsonb(obj) -> str:
    blob = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return f"{q(blob, 'j')}::jsonb"


def text_array(items: list[str]) -> str:
    if not items:
        return "'{}'::text[]"
    return "ARRAY[" + ", ".join(q(i) for i in items) + "]"


def nullable(value: str | None) -> str:
    return "NULL" if not value else q(value)


# ---------------------------------------------------------------------------
# 内容指纹：与 app/services/bank.content_hash 必须一致
# ---------------------------------------------------------------------------

try:  # 在 venv 里运行时直接用服务端实现，避免两套算法漂移
    sys.path.insert(0, str(BACKEND))
    from app.services.bank import content_hash  # type: ignore
except Exception:  # 退化为同算法副本
    import hashlib

    def content_hash(items) -> str:  # type: ignore[misc]
        blob = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# 读取与校验
# ---------------------------------------------------------------------------


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def build_questions() -> tuple[list[dict], list[int], str]:
    bundle = load("questions.json")
    questions = bundle["questions"]
    weights = bundle["bank"]["weights"]

    errors: list[str] = []
    if len(questions) != 80:
        errors.append(f"题目数量 {len(questions)}，期望 80")
    per_dim = {d: 0 for d in DIMS}
    for item in questions:
        per_dim[item["dim"]] += 1
        if len(item["options"]) != 5:
            errors.append(f"{item['id']}: 选项 {len(item['options'])} 个")
    for dim, count in per_dim.items():
        if count != 20:
            errors.append(f"{dim} 维度 {count} 题，期望 20")
    if errors:
        raise SystemExit("题库校验失败：\n  - " + "\n  - ".join(errors))

    return questions, weights, content_hash(questions)


def build_celebrities() -> list[dict]:
    items = load("celebrities.json")["celebrities"]
    if len(items) != 64:
        raise SystemExit(f"名人数量 {len(items)}，期望 64")
    return items


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------


def render_schema() -> str:
    return """-- ============================================================================
-- 01_schema.sql · MBTI 测试站建表脚本（PostgreSQL 15 / 16）
-- 幂等：可重复执行。执行顺序：01 → 02 → 03
-- ============================================================================

-- 题库：bank → version → question --------------------------------------------
CREATE TABLE IF NOT EXISTS question_bank (
    id                  BIGSERIAL    PRIMARY KEY,
    slug                VARCHAR(64)  NOT NULL UNIQUE,
    name                VARCHAR(64)  NOT NULL,
    current_version_id  BIGINT
);

CREATE TABLE IF NOT EXISTS bank_version (
    id              BIGSERIAL    PRIMARY KEY,
    bank_id         BIGINT       NOT NULL REFERENCES question_bank(id),
    version         INTEGER      NOT NULL,
    status          VARCHAR(16)  NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'published', 'archived')),
    question_count  INTEGER      NOT NULL DEFAULT 0,
    content_hash    VARCHAR(64)  NOT NULL DEFAULT '',
    published_at    TIMESTAMPTZ,
    UNIQUE (bank_id, version)
);

CREATE INDEX IF NOT EXISTS ix_bank_version_bank_status ON bank_version (bank_id, status);

CREATE TABLE IF NOT EXISTS question (
    id              BIGSERIAL    PRIMARY KEY,
    bank_version_id BIGINT       NOT NULL REFERENCES bank_version(id) ON DELETE CASCADE,
    code            VARCHAR(32)  NOT NULL,
    dim             VARCHAR(2)   NOT NULL CHECK (dim IN ('EI', 'SN', 'TF', 'JP')),
    type            VARCHAR(32)  NOT NULL,
    stem            TEXT         NOT NULL,
    payload         JSONB        NOT NULL,
    tags            TEXT[]       NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_question_version_code ON question (bank_version_id, code);
CREATE INDEX IF NOT EXISTS ix_question_dim  ON question (dim);
CREATE INDEX IF NOT EXISTS ix_question_tags ON question USING gin (tags);

-- 测试会话与作答 -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS test_session (
    id              UUID         PRIMARY KEY,
    bank_version_id BIGINT       NOT NULL REFERENCES bank_version(id),
    question_ids    BIGINT[]     NOT NULL,
    seed            BIGINT       NOT NULL DEFAULT 0,
    client          TEXT,
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ  NOT NULL,
    finished_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS answer (
    session_id  UUID         NOT NULL REFERENCES test_session(id) ON DELETE CASCADE,
    question_id BIGINT       NOT NULL,
    value       JSONB        NOT NULL,
    answered_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, question_id)
);

CREATE TABLE IF NOT EXISTS result (
    id          BIGSERIAL    PRIMARY KEY,
    session_id  UUID         NOT NULL UNIQUE REFERENCES test_session(id) ON DELETE CASCADE,
    share_id    VARCHAR(32)  NOT NULL UNIQUE,
    code        CHAR(4)      NOT NULL,
    ratios      JSONB        NOT NULL,
    answered    INTEGER      NOT NULL DEFAULT 0,
    total       INTEGER      NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_result_share ON result (share_id);

-- 历史名人（阶段二） ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS celebrity (
    id              VARCHAR(64)  PRIMARY KEY,
    name            VARCHAR(64)  NOT NULL,
    alias           VARCHAR(64),
    era             VARCHAR(64),
    region          VARCHAR(64),
    field           VARCHAR(64),
    type            VARCHAR(4)   NOT NULL,
    basis           VARCHAR(16)  NOT NULL DEFAULT 'inferred',
    confidence      REAL         NOT NULL DEFAULT 0.5,
    vector          JSONB        NOT NULL,
    traits          JSONB        NOT NULL DEFAULT '[]'::jsonb,
    why             TEXT         NOT NULL DEFAULT '',
    quote           TEXT,
    quote_source    VARCHAR(128),
    note            TEXT,
    portrait        JSONB        NOT NULL DEFAULT '{}'::jsonb,
    sources         JSONB        NOT NULL DEFAULT '[]'::jsonb,
    status          VARCHAR(16)  NOT NULL DEFAULT 'published',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_celebrity_type        ON celebrity (type);
CREATE INDEX IF NOT EXISTS ix_celebrity_type_status ON celebrity (type, status);
CREATE INDEX IF NOT EXISTS ix_celebrity_name        ON celebrity (name);

CREATE TABLE IF NOT EXISTS result_celebrity (
    id                BIGSERIAL    PRIMARY KEY,
    result_id         VARCHAR(32)  NOT NULL,
    algorithm_version VARCHAR(16)  NOT NULL DEFAULT 'v1',
    primary_id        VARCHAR(64),
    primary_score     REAL,
    payload           JSONB        NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_result_celebrity_result ON result_celebrity (result_id);
"""


def render_seed(questions: list[dict], weights: list[int], digest: str,
                celebrities: list[dict]) -> str:
    bank_id, version_id = 1, 1
    head = [
        "-- ============================================================================",
        "-- 02_seed.sql · 题库与名人数据（由 export_seed_sql.py 生成，勿手改）",
        f"-- 生成时间：{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"-- 内容指纹：{digest}",
        "-- 幂等：ON CONFLICT DO NOTHING，重复执行不会翻倍",
        "-- ============================================================================",
        "",
        "BEGIN;",
        "",
        "-- 题库本体 ----------------------------------------------------------------",
        "INSERT INTO question_bank (id, slug, name) VALUES",
        f"  ({bank_id}, {q('mbti-v1')}, {q('MBTI 基础题库')})",
        "ON CONFLICT (id) DO NOTHING;",
        "",
        "INSERT INTO bank_version (id, bank_id, version, status, question_count, content_hash, published_at)",
        "VALUES",
        f"  ({version_id}, {bank_id}, 1, 'published', {len(questions)}, {q(digest)}, now())",
        "ON CONFLICT (bank_id, version) DO NOTHING;",
        "",
        "-- 题目 --------------------------------------------------------------------",
        "INSERT INTO question (id, bank_version_id, code, dim, type, stem, payload, tags) VALUES",
    ]

    rows = []
    for index, item in enumerate(questions, start=1):
        payload = {
            "type": item.get("type", "likert5"),
            "options": item["options"],
            "weights": weights,
        }
        rows.append(
            f"  ({index}, {version_id}, {q(item['id'])}, {q(item['dim'])}, "
            f"{q(item.get('type', 'likert5'))}, {q(item['stem'])},\n"
            f"   {jsonb(payload)},\n"
            f"   {text_array(item.get('tags') or [])})"
        )

    mid = [
        ",\n".join(rows) + "",
        "ON CONFLICT (bank_version_id, code) DO NOTHING;",
        "",
        "-- 指向当前发布版本 --------------------------------------------------------",
        "UPDATE question_bank SET current_version_id = "
        f"{version_id} WHERE id = {bank_id};",
        "",
        "-- 序列对齐（显式 id 插入后必须做） ----------------------------------------",
        "SELECT setval(pg_get_serial_sequence('question', 'id'),"
        " GREATEST((SELECT COALESCE(MAX(id), 1) FROM question), 1));",
        "SELECT setval(pg_get_serial_sequence('bank_version', 'id'),"
        " GREATEST((SELECT COALESCE(MAX(id), 1) FROM bank_version), 1));",
        "SELECT setval(pg_get_serial_sequence('question_bank', 'id'),"
        " GREATEST((SELECT COALESCE(MAX(id), 1) FROM question_bank), 1));",
        "",
        "-- 历史名人（阶段二使用，不影响测试流程） ----------------------------------",
    ]

    celeb_rows = []
    for c in celebrities:
        portrait = c.get("portrait") or {}
        celeb_rows.append(
            f"  ({q(c['id'])}, {q(c['name'])}, {nullable(c.get('alias'))}, "
            f"{nullable(c.get('era'))}, {nullable(c.get('region'))}, "
            f"{nullable(c.get('field'))}, {q(c['type'])}, {q(c.get('basis', 'inferred'))}, "
            f"{float(c.get('confidence', 0.5))}, "
            f"{jsonb(c['vector'])}, {jsonb(c.get('traits') or [])}, "
            f"{q(c.get('why', ''))}, {nullable(c.get('quote'))}, "
            f"{nullable(c.get('quote_source'))}, {nullable(c.get('note'))}, "
            f"{jsonb(portrait)}, {jsonb(c.get('sources') or [])}, "
            f"{q(c.get('status', 'published'))}, now(), now())"
        )

    tail = [
        "INSERT INTO celebrity (id, name, alias, era, region, field, type, basis, confidence,",
        "                      vector, traits, why, quote, quote_source, note,",
        "                      portrait, sources, status, created_at, updated_at) VALUES",
        ",\n".join(celeb_rows),
        "ON CONFLICT (id) DO NOTHING;",
        "",
        "COMMIT;",
        "",
    ]

    return "\n".join(head + mid + tail)


def render_verify() -> str:
    return """-- ============================================================================
-- 03_verify.sql · 导入后自检
-- 期望：题 80 / 每维 20 / 版本 1 条 published / 名人 64
-- ============================================================================

\\echo '== 表数量（应为 8）'
SELECT count(*) AS tables
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('question_bank','bank_version','question','test_session',
                     'answer','result','celebrity','result_celebrity');

\\echo '== 题库版本'
SELECT b.slug, v.version, v.status, v.question_count, v.content_hash
FROM question_bank b JOIN bank_version v ON v.id = b.current_version_id;

\\echo '== 题目总数与维度分布'
SELECT dim, count(*) AS n FROM question GROUP BY dim ORDER BY dim;

\\echo '== 选项数是否都是 5'
SELECT count(*) FILTER (WHERE jsonb_array_length(payload->'options') = 5) AS ok_5_options,
       count(*) AS total
FROM question;

\\echo '== 题型分布'
SELECT type, count(*) FROM question GROUP BY type;

\\echo '== 名人覆盖（16 型 × 每型人数）'
SELECT type, count(*) AS n FROM celebrity GROUP BY type ORDER BY type;

\\echo '== 抽样一题'
SELECT code, dim, stem, payload->'options'->>0 AS option_a, tags
FROM question ORDER BY id LIMIT 1;
"""


def main() -> int:
    questions, weights, digest = build_questions()
    celebrities = build_celebrities()

    SQL_DIR.mkdir(parents=True, exist_ok=True)
    (SQL_DIR / "01_schema.sql").write_text(render_schema(), encoding="utf-8")
    (SQL_DIR / "02_seed.sql").write_text(
        render_seed(questions, weights, digest, celebrities), encoding="utf-8"
    )
    (SQL_DIR / "03_verify.sql").write_text(render_verify(), encoding="utf-8")

    sizes = {p.name: p.stat().st_size for p in sorted(SQL_DIR.glob("0*.sql"))}
    print("✓ 已生成：")
    for name, size in sizes.items():
        print(f"   {name:<16} {size / 1024:.1f} KB")
    print(f"\n题目 {len(questions)} 道，名人 {len(celebrities)} 位，内容指纹 {digest}")
    print(f"输出目录：{SQL_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
