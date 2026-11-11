"""计分聚合的 golden case。

不依赖数据库与 Web 框架：题目用 SimpleNamespace 打桩，只验证算术。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.scoring  # noqa: E402,F401  触发题型注册
from app.core.exceptions import UnsupportedQuestionType  # noqa: E402
from app.services.scoring import aggregate, strength  # noqa: E402

DIMS = ("EI", "SN", "TF", "JP")


def make_questions(per_dim: int = 10) -> list[SimpleNamespace]:
    questions: list[SimpleNamespace] = []
    qid = 1
    for dim in DIMS:
        for i in range(per_dim):
            questions.append(
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
    return questions


def pick(questions, index: int) -> dict:
    return {q.id: {"index": index} for q in questions}


class ScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.questions = make_questions()
        self.qmap = {q.id: q for q in self.questions}

    def test_all_left(self) -> None:
        code, ratios = aggregate(pick(self.questions, 0), self.qmap)
        self.assertEqual(code, "ESTJ")
        for dim in DIMS:
            self.assertAlmostEqual(ratios[dim], -1.0)
        self.assertEqual(strength(ratios["EI"]), 100)

    def test_all_right(self) -> None:
        code, ratios = aggregate(pick(self.questions, 4), self.qmap)
        self.assertEqual(code, "INFP")
        for dim in DIMS:
            self.assertAlmostEqual(ratios[dim], 1.0)

    def test_all_neutral_falls_back_to_left_pole(self) -> None:
        code, ratios = aggregate(pick(self.questions, 2), self.qmap)
        self.assertEqual(code, "ESTJ")
        for dim in DIMS:
            self.assertAlmostEqual(ratios[dim], 0.0)
        self.assertEqual(strength(ratios["EI"]), 50)

    def test_balanced_five_five(self) -> None:
        answers: dict = {}
        for dim in DIMS:
            group = [q for q in self.questions if q.dim == dim]
            for q in group[:5]:
                answers[q.id] = {"index": 0}     # -2
            for q in group[5:]:
                answers[q.id] = {"index": 4}     # +2
        code, ratios = aggregate(answers, self.qmap)
        self.assertEqual(code, "ESTJ")
        self.assertAlmostEqual(ratios["SN"], 0.0)

    def test_six_four_is_minus_point_two(self) -> None:
        answers: dict = {}
        for dim in DIMS:
            group = [q for q in self.questions if q.dim == dim]
            for q in group[:6]:
                answers[q.id] = {"index": 0}     # -2 ×6 = -12
            for q in group[6:]:
                answers[q.id] = {"index": 4}     # +2 ×4 = +8
        _, ratios = aggregate(answers, self.qmap)
        self.assertAlmostEqual(ratios["EI"], -0.2, places=6)
        self.assertEqual(strength(ratios["EI"]), 60)

    def test_partial_answers_only_count_answered(self) -> None:
        answers = pick(self.questions[:37], 0)   # 只答 37 题
        code, ratios = aggregate(answers, self.qmap)
        self.assertEqual(code, "ESTJ")
        for dim in DIMS:
            self.assertAlmostEqual(ratios[dim], -1.0)

    def test_unknown_type_raises(self) -> None:
        ghost = SimpleNamespace(id=9999, code="zz_1", dim="EI", type="mystery",
                                stem="", tags=[], payload={"options": ["a", "b"]})
        with self.assertRaises(UnsupportedQuestionType):
            aggregate({9999: {"index": 0}}, {9999: ghost})

    def test_choice2_registered_and_scored(self) -> None:
        from app.scoring import get

        scorer = get("choice2")
        q = SimpleNamespace(
            code="t_1", dim="EI", type="choice2", stem="", tags=[],
            payload={"options": ["A", "B"], "deltas": [{"EI": -2}, {"EI": 2}]},
        )
        self.assertEqual(scorer.score(q, {"index": 1}), {"EI": 2.0})
        self.assertEqual(scorer.cap(q), {"EI": 2.0})


if __name__ == "__main__":
    unittest.main(verbosity=2)
