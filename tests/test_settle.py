"""结算的纯函数部分：答案映射、缺答、非法 code。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.settle import compute  # noqa: E402

DIMS = ("EI", "SN", "TF", "JP")


def build(per_dim: int = 10) -> list[SimpleNamespace]:
    pool: list[SimpleNamespace] = []
    qid = 1
    for dim in DIMS:
        for i in range(per_dim):
            pool.append(
                SimpleNamespace(
                    id=qid,
                    code=f"{dim.lower()}_{i + 1}",
                    dim=dim,
                    type="likert5",
                    stem="",
                    tags=["日常"],
                    payload={"options": ["a", "b", "c", "d", "e"], "weights": [-2, -1, 0, 1, 2]},
                )
            )
            qid += 1
    return pool


class ComputeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.questions = build()

    def test_full_answers(self) -> None:
        answers = {q.code: 4 for q in self.questions}      # 全选 e → INFP
        computed = compute(answers, self.questions)
        self.assertEqual(computed.code, "INFP")
        self.assertEqual(computed.answered, 40)
        self.assertEqual(computed.total, 40)

    def test_partial_answers(self) -> None:
        answers = {q.code: 0 for q in self.questions[:37]}
        computed = compute(answers, self.questions)
        self.assertEqual(computed.answered, 37)
        self.assertEqual(computed.total, 40)
        self.assertEqual(computed.code, "ESTJ")

    def test_unknown_code_ignored(self) -> None:
        answers = {q.code: 0 for q in self.questions}
        answers["not_a_question"] = 3
        computed = compute(answers, self.questions)
        self.assertEqual(computed.answered, 40)

    def test_empty_answers(self) -> None:
        computed = compute({}, self.questions)
        self.assertEqual(computed.answered, 0)
        self.assertEqual(computed.code, "ESTJ")          # 全 0 → 左极
        self.assertEqual(computed.ratios["EI"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
