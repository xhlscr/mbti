"""抽题：数量、分布、可复现、题量不足。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.draw import draw  # noqa: E402

DIMS = ("EI", "SN", "TF", "JP")
TAGS = ["社交", "工作", "独处", "旅行", "日常"]


def build(per_dim: int = 20) -> list[SimpleNamespace]:
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
                    tags=[TAGS[i % len(TAGS)]],
                    payload={"options": ["a", "b", "c", "d", "e"], "weights": [-2, -1, 0, 1, 2]},
                )
            )
            qid += 1
    return pool


class DrawTests(unittest.TestCase):
    def test_counts_and_balance(self) -> None:
        picked = draw(build(), per_dim=10, seed=42)
        self.assertEqual(len(picked), 40)
        self.assertEqual(len({q.id for q in picked}), 40, "出现重复题目")
        for dim in DIMS:
            self.assertEqual(sum(1 for q in picked if q.dim == dim), 10)

    def test_same_seed_is_reproducible(self) -> None:
        a = [q.code for q in draw(build(), 10, 2024)]
        b = [q.code for q in draw(build(), 10, 2024)]
        self.assertEqual(a, b)

    def test_different_seed_differs(self) -> None:
        a = [q.code for q in draw(build(), 10, 1)]
        b = [q.code for q in draw(build(), 10, 2)]
        self.assertNotEqual(a, b)

    def test_tag_diversity(self) -> None:
        picked = draw(build(), per_dim=10, seed=7)
        for dim in DIMS:
            tags = {q.tags[0] for q in picked if q.dim == dim}
            self.assertGreaterEqual(len(tags), 3, f"{dim} 维抽题场景过于集中：{tags}")

    def test_insufficient_raises(self) -> None:
        with self.assertRaises(ValueError):
            draw(build(per_dim=4), per_dim=10, seed=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
