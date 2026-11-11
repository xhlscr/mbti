"""内容产物回归测试：守住 `backend/app/data/*.json` 的结构。

源 Markdown 一旦被改动（改题、加题、改文案），重跑 `import_content.py` 后这里必须仍然全绿。
"""

from __future__ import annotations

import json
import sys
import unittest
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
DATA = BACKEND / "app" / "data"

sys.path.insert(0, str(BACKEND))

from app.matching.celebrity import ALL_TYPES  # noqa: E402

DIMS = ("EI", "SN", "TF", "JP")
FUNCS = {"Se", "Si", "Ne", "Ni", "Te", "Ti", "Fe", "Fi"}


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


class QuestionBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = load("questions.json")
        cls.questions = cls.bank["questions"]

    def test_bank_meta(self):
        self.assertEqual(self.bank["schema_version"], 1)
        self.assertEqual(self.bank["bank"]["per_dim"], 10)
        self.assertEqual(self.bank["bank"]["weights"], [-2, -1, 0, 1, 2])

    def test_count_and_balance(self):
        self.assertEqual(len(self.questions), 80)
        dist = Counter(q["dim"] for q in self.questions)
        for dim in DIMS:
            self.assertEqual(dist[dim], 20, f"{dim} 题数不是 20")

    def test_ids_unique_and_consistent(self):
        ids = [q["id"] for q in self.questions]
        self.assertEqual(len(ids), len(set(ids)), "题目 id 重复")
        for q in self.questions:
            self.assertEqual(q["id"].split("_")[0].upper()[:2] in
                             ("EI", "SN", "TF", "JP"), True, f"{q['id']} 前缀异常")
            self.assertEqual(q["type"], "likert5")
            self.assertEqual(len(q["options"]), 5, f"{q['id']} 选项不是 5 个")
            self.assertTrue(all(o.strip() for o in q["options"]), f"{q['id']} 有空选项")
            self.assertTrue(q["stem"].strip(), f"{q['id']} 空题干")
            self.assertNotIn("**", q["stem"], f"{q['id']} 题干残留 markdown")

    def test_tags_present(self):
        for q in self.questions:
            self.assertTrue(1 <= len(q["tags"]) <= 3, f"{q['id']} 标签数异常：{q['tags']}")


class TypeBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.types = load("types.json")
        cls.funcs = load("functions.json")

    def test_coverage(self):
        self.assertEqual(set(self.types), set(ALL_TYPES), "类型文案覆盖不全")
        self.assertEqual(set(self.funcs), set(ALL_TYPES), "功能栈覆盖不全")

    def test_fields_non_empty(self):
        for code, t in self.types.items():
            self.assertEqual(t["code"], code)
            self.assertTrue(t["name"])
            self.assertGreater(len(t["overview"]), 20, f"{code} 概述太短")
            self.assertGreaterEqual(len(t["traits"]), 3, f"{code} 核心特质过少")
            self.assertGreaterEqual(len(t["careers"]), 3, f"{code} 职业方向过少")
            self.assertGreaterEqual(len(t["growth"]), 2, f"{code} 成长建议过少")
            for item in t["traits"] + t["growth"]:
                self.assertNotIn("---", item, f"{code} 字段混入了分隔线")

    def test_function_stacks(self):
        for code, f in self.funcs.items():
            stack = [f["dom"], f["aux"], f["tert"], f["inf"]]
            self.assertTrue(set(stack) <= FUNCS, f"{code} 存在非法功能码 {stack}")
            self.assertEqual(len(set(stack)), 4, f"{code} 功能栈重复 {stack}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
