#!/usr/bin/env python
"""把 02_seed.sql 反向解析成结构化数据，与 app/data/*.json 逐字段比对。

没有可用数据库时，这是验证种子脚本最可靠的方式：
SQL 文本 → 词法解析 → 行/列 → 与源内容对比。

    python backend/scripts/check_seed_sql.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DATA = BACKEND / "app" / "data"
SQL_DIR = BACKEND / "sql"

DIMS = ("EI", "SN", "TF", "JP")


# ---------------------------------------------------------------------------
# 极简 SQL 值解析器：只支持本文件用到的语法
#   $tag$...$tag$ / '...' / ARRAY[...] / NULL / 数字 / now() / ::jsonb / ::text[]
# ---------------------------------------------------------------------------


class ParseError(Exception):
    pass


def _skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def _read_dollar(s: str, i: int) -> tuple[str, int]:
    m = re.match(r"\$([A-Za-z_]\w*)?\$", s[i:])
    if not m:
        raise ParseError(f"非法 dollar quote @{i}: {s[i:i + 20]!r}")
    tag = m.group(0)
    start = i + len(tag)
    end = s.find(tag, start)
    if end < 0:
        raise ParseError(f"未闭合的 dollar quote: {tag}")
    return s[start:end], end + len(tag)


def _read_single(s: str, i: int) -> tuple[str, int]:
    assert s[i] == "'"
    i += 1
    out = []
    while i < len(s):
        if s[i] == "'":
            if i + 1 < len(s) and s[i + 1] == "'":   # '' 转义
                out.append("'")
                i += 2
                continue
            return "".join(out), i + 1
        out.append(s[i])
        i += 1
    raise ParseError("未闭合的单引号")


def _read_value(s: str, i: int):
    i = _skip_ws(s, i)
    if i >= len(s):
        raise ParseError("意外的结尾")
    ch = s[i]

    if ch == "$":
        value, i = _read_dollar(s, i)
    elif ch == "'":
        value, i = _read_single(s, i)
    elif s.startswith("ARRAY[", i):
        i += len("ARRAY[")
        items = []
        i = _skip_ws(s, i)
        if s[i] == "]":
            i += 1
        else:
            while True:
                item, i = _read_value(s, i)
                items.append(item)
                i = _skip_ws(s, i)
                if s[i] == ",":
                    i += 1
                    continue
                if s[i] == "]":
                    i += 1
                    break
                raise ParseError(f"ARRAY 内意外字符 {s[i]!r}")
        value = items
    elif s.startswith("NULL", i):
        value, i = None, i + 4
    elif s.startswith("now()", i):
        value, i = "now()", i + 5
    else:
        m = re.match(r"[-\d.]+|[A-Za-z_]\w*", s[i:])
        if not m:
            raise ParseError(f"无法识别的值 @{i}: {s[i:i + 20]!r}")
        value, i = m.group(0), i + len(m.group(0))

    # 跳过类型转换
    i = _skip_ws(s, i)
    if s.startswith("::", i):
        m = re.match(r"::[A-Za-z_ ]+(\[\])?", s[i:])
        if not m:
            raise ParseError("非法类型转换")
        i += len(m.group(0))
    return value, i


def parse_rows(sql: str, table: str) -> list[list]:
    start = sql.index(f"INSERT INTO {table} (")
    body = sql[start:]
    # 跳到 VALUES 之后
    values_at = body.index("VALUES")
    i = _skip_ws(body, values_at + len("VALUES"))
    rows: list[list] = []
    while True:
        i = _skip_ws(body, i)
        if body[i] != "(":
            break
        i += 1
        row = []
        while True:
            value, i = _read_value(body, i)
            row.append(value)
            i = _skip_ws(body, i)
            if body[i] == ",":
                i += 1
                continue
            if body[i] == ")":
                i += 1
                break
            raise ParseError(f"{table}: 行内意外字符 {body[i]!r}")
        rows.append(row)
        i = _skip_ws(body, i)
        if body[i] == ",":
            i += 1
            continue
        break
    return rows


# ---------------------------------------------------------------------------
# 比对
# ---------------------------------------------------------------------------


def main() -> int:
    sql = (SQL_DIR / "02_seed.sql").read_text(encoding="utf-8")
    bundle = json.loads((DATA / "questions.json").read_text(encoding="utf-8"))
    celebs = json.loads((DATA / "celebrities.json").read_text(encoding="utf-8"))["celebrities"]
    weights = bundle["bank"]["weights"]
    problems: list[str] = []

    # 1) 题目
    q_rows = parse_rows(sql, "question")
    if len(q_rows) != 80:
        problems.append(f"题目行数 {len(q_rows)}，期望 80")
    for idx, (row, src) in enumerate(zip(q_rows, bundle["questions"]), start=1):
        expect = [
            str(idx), "1", src["id"], src["dim"], src.get("type", "likert5"), src["stem"],
        ]
        got = [str(x) for x in row[:6]]
        if got != expect:
            problems.append(f"第 {idx} 行标识不一致：{got} != {expect}")
            continue
        payload = row[6]
        try:
            parsed = json.loads(payload)
        except Exception as exc:
            problems.append(f"{src['id']}: payload 不是合法 JSON（{exc}）")
            continue
        if parsed.get("options") != src["options"]:
            problems.append(f"{src['id']}: options 不一致")
        if parsed.get("weights") != weights:
            problems.append(f"{src['id']}: weights 不一致")
        if parsed.get("type") != src.get("type", "likert5"):
            problems.append(f"{src['id']}: payload.type 不一致")
        if row[7] != (src.get("tags") or []):
            problems.append(f"{src['id']}: tags 不一致 {row[7]} != {src.get('tags')}")

    # 2) 名人
    c_rows = parse_rows(sql, "celebrity")
    if len(c_rows) != 64:
        problems.append(f"名人行数 {len(c_rows)}，期望 64")
    for row, src in zip(c_rows, celebs):
        if row[0] != src["id"] or row[1] != src["name"] or row[6] != src["type"]:
            problems.append(f"名人 {src['id']}: 基础字段不一致")
            continue
        if abs(float(row[8]) - float(src.get("confidence", 0.5))) > 1e-6:
            problems.append(f"名人 {src['id']}: confidence 不一致")
        if json.loads(row[9]) != src["vector"]:
            problems.append(f"名人 {src['id']}: vector 不一致")
        if json.loads(row[10]) != (src.get("traits") or []):
            problems.append(f"名人 {src['id']}: traits 不一致")
        if row[11] != src.get("why", ""):
            problems.append(f"名人 {src['id']}: why 不一致")

    # 3) 结构完整性
    for needle, label in [
        ("INSERT INTO question_bank", "question_bank 插入"),
        ("INSERT INTO bank_version", "bank_version 插入"),
        ("UPDATE question_bank SET current_version_id", "当前版本指向"),
        ("setval(pg_get_serial_sequence('question'", "question 序列对齐"),
        ("COMMIT;", "事务提交"),
    ]:
        if needle not in sql:
            problems.append(f"缺少：{label}")

    # 4) dollar quote 配对
    for tag in ("$s$", "$j$", "$t$"):
        if sql.count(tag) % 2:
            problems.append(f"{tag} 数量为奇数，存在未闭合字符串")

    if problems:
        print(f"✗ 发现 {len(problems)} 个问题：", file=sys.stderr)
        for p in problems[:30]:
            print(f"  - {p}", file=sys.stderr)
        return 1

    dims = {}
    for src in bundle["questions"]:
        dims[src["dim"]] = dims.get(src["dim"], 0) + 1
    print("✓ 02_seed.sql 解析通过")
    print(f"   题目 {len(q_rows)} 行，维度分布 {dims}")
    print(f"   名人 {len(c_rows)} 行，类型覆盖 {len({c['type'] for c in celebs})}/16")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
