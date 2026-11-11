#!/usr/bin/env python
"""把仓库根目录的三份 Markdown 源文件解析成前端/后端可用的 JSON。

    python api/scripts/import_content.py                 # 默认输出到 api/app/data/
    python api/scripts/import_content.py --retag         # 重新生成自动标签（会覆盖手工修改）
    python api/scripts/import_content.py --src . --out api/app/data

产物（默认写入 api/app/data/）：
    questions.json   80 题（含自动建议的 tags，可手工改）
    types.json       16 型文案
    functions.json   16 型认知功能栈
    tags-review.md   待人工确认的标签清单

设计要点：
1. **幂等**：已存在的 questions.json 里手工改过的 tags 会被保留，重跑不会覆盖；
2. **硬校验**：数量、维度分布、选项数、id 唯一、功能栈合法性，任一不过直接退出；
3. 不臆造源文件里没有的内容（比如 tagline 留空），避免"看起来有、其实是编的"。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

DIMS = ("EI", "SN", "TF", "JP")
DIM_BY_PREFIX = {"ei": "EI", "sn": "SN", "tf": "TF", "jp": "JP"}
FUNCS = {"Se", "Si", "Ne", "Ni", "Te", "Ti", "Fe", "Fi"}
ALL_TYPES = tuple(
    a + b + c + d
    for a in "EI"
    for b in "SN"
    for c in "TF"
    for d in "JP"
)

QUESTION_RE = re.compile(
    r"### 题目 \(id: `(\w+)`\)\n\*\*(.+?)\*\*\n((?:- `[a-e]` .*\n)+)"
)
TYPE_RE = re.compile(r"^## ([A-Z]{4}) — (.+)$", re.M)
STACK_RE = re.compile(r"^### ([A-Z]{4}) — (.+)$", re.M)

TYPE_FIELDS = ("概述", "核心特质", "适合的职业方向", "人际关系", "成长建议")

# 关键词 → 标签。规则粗糙但够用，目的只是把 2 小时的人工打分压到 20 分钟复核。
TAG_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("社交", ("朋友", "聚会", "团建", "同事", "邻居", "派对", "生日", "新朋友", "打招呼", "聚餐", "聊天", "社交")),
    ("独处", ("一个人", "独处", "安静", "自己待", "不被打扰", "独自")),
    ("工作", ("工作", "汇报", "截止", "领导", "客户", "面试", "方案", "同事", "加班", "会议", "升职")),
    ("学习", ("学习", "读书", "课程", "培训", "考试", "技能", "看书", "读一本")),
    ("消费", ("买", "购物", "超市", "网购", "快递", "礼物", "价格", "性价比", "菜单", "评价")),
    ("旅行", ("旅行", "出差", "酒店", "景点", "行程", "攻略", "博物馆", "展览", "出游")),
    ("情绪", ("难过", "感动", "生气", "安慰", "倾诉", "失恋", "同情", "难受", "哭", "愤怒",
              "慈善", "募捐", "捐")),
    ("冲突", ("矛盾", "拒绝", "投诉", "争执", "失误", "评理", "指出", "尴尬", "吵")),
    ("决策", ("决定", "选择", "判断", "计划", "规划", "安排", "目标", "评估", "取舍")),
    ("审美", ("画", "诗", "音乐", "设计", "装饰", "氛围", "风格", "艺术", "好看", "美")),
    ("抽象", ("哲学", "意义", "未来", "规律", "原理", "可能性", "想法", "联想", "梦", "象征", "本质")),
    ("日常", ("吃饭", "手机", "衣柜", "整理", "房间", "周末", "早上", "放假", "起床", "睡",
              "路上", "招牌", "路人", "穿着", "游戏", "邮件", "消息", "回复", "收拾")),
]


def fail(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def parse_questions(text: str) -> list[dict]:
    blocks = QUESTION_RE.findall(text)
    if not blocks:
        fail("questions.md 里没匹配到任何题目，检查标题格式是否为 `### 题目 (id: `ei_1`)`")

    questions = []
    for qid, stem, body in blocks:
        options = re.findall(r"- `[a-e]` (.+)", body)
        prefix = qid.split("_")[0]
        if prefix not in DIM_BY_PREFIX:
            fail(f"{qid}: id 前缀 {prefix!r} 无法映射到维度")
        questions.append(
            {
                "id": qid,
                "dim": DIM_BY_PREFIX[prefix],
                "type": "likert5",
                "stem": stem.strip(),
                "options": [o.strip() for o in options],
                "tags": suggest_tags(stem + "".join(options)),
            }
        )
    return questions


def suggest_tags(text: str) -> list[str]:
    hits = [(tag, sum(1 for kw in kws if kw in text)) for tag, kws in TAG_RULES]
    hits = [(tag, n) for tag, n in hits if n > 0]
    hits.sort(key=lambda x: (-x[1], x[0]))
    return [tag for tag, _ in hits[:2]] or ["其他"]


def parse_types(text: str) -> dict[str, dict]:
    matches = list(TYPE_RE.finditer(text))
    if not matches:
        fail("types.md 里没匹配到类型块，检查标题格式是否为 `## INTJ — 建筑师`")

    out: dict[str, dict] = {}
    for i, m in enumerate(matches):
        code, alias = m.group(1), m.group(2).strip()
        body = text[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        body = body.split("\n---")[0]      # 去掉块尾分隔线，否则会混进最后一个字段

        fields: dict[str, str] = {}
        parts = re.split(r"\*\*(概述|核心特质|适合的职业方向|人际关系|成长建议)：\*\*", body)
        for j in range(1, len(parts) - 1, 2):
            fields[parts[j]] = parts[j + 1].strip()

        missing = [f for f in TYPE_FIELDS if f not in fields]
        if missing:
            fail(f"{code}: 缺少字段 {missing}")

        traits = [
            line.lstrip("- ").strip()
            for line in fields["核心特质"].splitlines()
            if line.strip().startswith("-")
        ]
        careers = [c.strip("。 ") for c in fields["适合的职业方向"].split("、") if c.strip()]
        growth = [
            x.strip("。 ")
            for x in re.split(r"[；;]", fields["成长建议"])
            if x.strip("。 ")
        ]

        out[code] = {
            "code": code,
            "name": alias,
            "overview": " ".join(fields["概述"].split()),
            "traits": traits,
            "careers": careers,
            "relationships": " ".join(fields["人际关系"].split()),
            "growth": growth,
        }
    return out


def parse_functions(text: str) -> dict[str, dict]:
    matches = list(STACK_RE.finditer(text))
    if not matches:
        fail("cognitive-functions.md 里没匹配到功能栈，检查标题格式是否为 `### ISTJ — 检查官`")

    out: dict[str, dict] = {}
    for i, m in enumerate(matches):
        code = m.group(1)
        body = text[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(text)]

        slot: dict[str, str] = {}
        for pos, fn in re.findall(r"\| (主导|辅助|第三|劣势) \| ([A-Z][a-z])（", body):
            slot[{"主导": "dom", "辅助": "aux", "第三": "tert", "劣势": "inf"}[pos]] = fn

        missing = [k for k in ("dom", "aux", "tert", "inf") if k not in slot]
        if missing:
            fail(f"{code}: 功能栈缺少 {missing}")

        note = ""
        note_match = re.search(r"\*\*功能运作简述：\*\*\s*(.+)", body)
        if note_match:
            note = " ".join(note_match.group(1).split())

        out[code] = {"code": code, **slot, "note": note}
    return out


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def validate(questions: list[dict], types: dict, functions: dict) -> None:
    errors: list[str] = []

    # 题目
    if len(questions) != 80:
        errors.append(f"题目总数是 {len(questions)}，期望 80")
    dist = Counter(q["dim"] for q in questions)
    for dim in DIMS:
        if dist[dim] != 20:
            errors.append(f"{dim} 维度有 {dist[dim]} 题，期望 20")

    ids = [q["id"] for q in questions]
    dup = [i for i, n in Counter(ids).items() if n > 1]
    if dup:
        errors.append(f"题目 id 重复：{dup}")

    for q in questions:
        if len(q["options"]) != 5:
            errors.append(f"{q['id']}: 选项 {len(q['options'])} 个，期望 5")
        if any(not o for o in q["options"]):
            errors.append(f"{q['id']}: 存在空选项")
        if not q["stem"]:
            errors.append(f"{q['id']}: 空题干")
        if q["id"].split("_")[0] not in DIM_BY_PREFIX:
            errors.append(f"{q['id']}: id 前缀非法")

    # 类型文案
    if set(types) != set(ALL_TYPES):
        errors.append(f"类型文案覆盖不全，缺 {sorted(set(ALL_TYPES) - set(types))}")
    for code, t in types.items():
        for key in ("overview", "traits", "careers", "relationships", "growth"):
            if not t.get(key):
                errors.append(f"{code}: 字段 {key} 为空")
        if len(t.get("traits", [])) < 3:
            errors.append(f"{code}: 核心特质只有 {len(t.get('traits', []))} 条，建议 ≥3")

    # 功能栈
    if set(functions) != set(ALL_TYPES):
        errors.append(f"功能栈覆盖不全，缺 {sorted(set(ALL_TYPES) - set(functions))}")
    for code, f in functions.items():
        stack = [f["dom"], f["aux"], f["tert"], f["inf"]]
        bad = [x for x in stack if x not in FUNCS]
        if bad:
            errors.append(f"{code}: 非法功能码 {bad}")
        if len(set(stack)) != 4:
            errors.append(f"{code}: 功能栈内有重复 {stack}")

    if errors:
        print(f"\n✗ 校验失败，共 {len(errors)} 个问题：", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=repo)
    ap.add_argument("--out", type=Path, default=repo / "backend" / "app" / "data")
    ap.add_argument("--retag", action="store_true", help="重新生成自动标签，覆盖手工修改")
    args = ap.parse_args()

    q_text = (args.src / "questions.md").read_text(encoding="utf-8")
    t_text = (args.src / "types.md").read_text(encoding="utf-8")
    f_text = (args.src / "cognitive-functions.md").read_text(encoding="utf-8")

    questions = parse_questions(q_text)
    types = parse_types(t_text)
    functions = parse_functions(f_text)

    # 幂等：保留上一次手工改过的 tags
    q_path = args.out / "questions.json"
    kept = 0
    if q_path.exists() and not args.retag:
        old = json.loads(q_path.read_text(encoding="utf-8"))
        old_tags = {q["id"]: q.get("tags", []) for q in old.get("questions", [])}
        for q in questions:
            if old_tags.get(q["id"]):
                q["tags"] = old_tags[q["id"]]
                kept += 1

    validate(questions, types, functions)

    args.out.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "bank": {"slug": "mbti-v1", "version": 1, "per_dim": 10, "weights": [-2, -1, 0, 1, 2]},
        "questions": questions,
    }
    (args.out / "questions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.out / "types.json").write_text(
        json.dumps(types, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.out / "functions.json").write_text(
        json.dumps(functions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # 标签复核清单
    lines = [
        "# 题目标签复核清单",
        "",
        f"共 {len(questions)} 题。自动标签只是关键词初筛，**请按真实场景修改 `questions.json` 里的 `tags`**，",
        "每题保留 2–3 个即可；重跑脚本不会覆盖你改过的值（除非加 `--retag`）。",
        "",
        "| id | 维度 | 题干 | 自动标签 |",
        "|---|---|---|---|",
    ]
    for q in questions:
        stem = q["stem"].replace("|", "｜")
        lines.append(f"| `{q['id']}` | {q['dim']} | {stem} | {'、'.join(q['tags']) or '—'} |")
    (args.out / "tags-review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 汇报
    dist = Counter(q["dim"] for q in questions)
    untagged = [q["id"] for q in questions if not q["tags"]]
    print(f"✓ questions.json   {len(questions)} 题  " + "  ".join(f"{d}={dist[d]}" for d in DIMS))
    print(f"✓ types.json       {len(types)} 型")
    print(f"✓ functions.json   {len(functions)} 套功能栈")
    print(f"✓ tags-review.md   待复核")
    if kept:
        print(f"· 保留了 {kept} 条手工标签")
    if untagged:
        print(f"⚠ {len(untagged)} 题没匹配到标签：{untagged[:8]}{' …' if len(untagged) > 8 else ''}")
    print(f"\n输出目录：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
