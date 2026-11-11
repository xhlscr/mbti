"""端到端业务链路（无数据库、无 HTTP）。

用生产内容跑一遍：抽题 → 作答 → 计分 → 判型，验证数据与算法接得上。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.scoring  # noqa: E402,F401  注册题型
from app.services.draw import draw  # noqa: E402
from app.services.scoring import strength  # noqa: E402
from app.services.settle import compute  # noqa: E402

DATA = BACKEND / "app" / "data" / "questions.json"


def load_questions() -> tuple[list[SimpleNamespace], list[int]]:
    bundle = json.loads(DATA.read_text(encoding="utf-8"))
    weights = bundle["bank"]["weights"]
    questions = [
        SimpleNamespace(
            id=index + 1,
            code=item["id"],
            dim=item["dim"],
            type=item["type"],
            stem=item["stem"],
            tags=item.get("tags") or [],
            payload={"options": item["options"], "weights": weights},
        )
        for index, item in enumerate(bundle["questions"])
    ]
    return questions, weights


class FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.questions, cls.weights = load_questions()

    def test_full_flow_all_left(self) -> None:
        """全选 a：应得 ESTJ，四维各 -100%。"""
        picked = draw(self.questions, per_dim=10, seed=42)
        self.assertEqual(len(picked), 40)
        answers = {q.code: 0 for q in picked}

        computed = compute(answers, picked)
        self.assertEqual(computed.code, "ESTJ")
        self.assertEqual(computed.answered, 40)
        for dim, ratio in computed.ratios.items():
            self.assertAlmostEqual(ratio, -1.0, places=6, msg=f"{dim} 比率异常")

    def test_full_flow_all_right(self) -> None:
        picked = draw(self.questions, per_dim=10, seed=7)
        computed = compute({q.code: 4 for q in picked}, picked)
        self.assertEqual(computed.code, "INFP")
        for ratio in computed.ratios.values():
            self.assertAlmostEqual(ratio, 1.0, places=6)

    def test_full_flow_neutral(self) -> None:
        picked = draw(self.questions, per_dim=10, seed=1)
        computed = compute({q.code: 2 for q in picked}, picked)
        self.assertEqual(computed.code, "ESTJ")          # 全 0 → 左极
        for ratio in computed.ratios.values():
            self.assertAlmostEqual(ratio, 0.0)
            self.assertEqual(strength(ratio), 50)

    def test_mixed_answers_are_coherent(self) -> None:
        """混合作答：类型码与比率方向必须一致。"""
        picked = draw(self.questions, per_dim=10, seed=99)
        answers = {}
        for i, q in enumerate(picked):
            answers[q.code] = (i % 5)                     # 循环 a~e

        computed = compute(answers, picked)
        self.assertEqual(len(computed.code), 4)
        for i, dim in enumerate(("EI", "SN", "TF", "JP")):
            letter = computed.code[i]
            ratio = computed.ratios[dim]
            if ratio > 0:
                self.assertIn(letter, {"I", "N", "F", "P"})
            elif ratio < 0:
                self.assertIn(letter, {"E", "S", "T", "J"})

    def test_every_question_is_scorable(self) -> None:
        """生产题库里每一道题都必须能被 scorer 处理，不能有漏网的题型。"""
        from app.scoring import get

        for q in self.questions:
            scorer = get(q.type)                          # 未注册会抛
            for index in range(len(q.payload["options"])):
                delta = scorer.score(q, {"index": index})
                self.assertEqual(set(delta), {q.dim})
                self.assertLessEqual(abs(delta[q.dim]), 2.0)
            self.assertEqual(scorer.cap(q), {q.dim: 2.0})


if __name__ == "__main__":
    unittest.main(verbosity=2)
