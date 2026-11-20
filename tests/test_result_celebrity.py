"""结果页名人匹配：快照计算与降级逻辑。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.result_celebrity import build_snapshot  # noqa: E402

RATIOS = {"EI": -0.8, "SN": -0.7, "TF": -0.9, "JP": -0.6}


class ResultCelebrityTests(unittest.TestCase):
    def test_snapshot_has_primary(self) -> None:
        snap = build_snapshot("ESTJ", RATIOS)
        self.assertIsNotNone(snap)
        assert snap is not None
        self.assertIn("primary", snap)
        if snap["primary"]:
            p = snap["primary"]
            self.assertIn("name", p)
            self.assertIn("percent", p)
            self.assertIn("match_notes", p)
            self.assertIsInstance(p["percent"], int)

    def test_also_capped(self) -> None:
        snap = build_snapshot("INTJ", {"EI": 0.9, "SN": 0.8, "TF": 0.9, "JP": 0.7})
        self.assertIsNotNone(snap)
        assert snap is not None
        self.assertLessEqual(len(snap.get("also", [])), 2)

    def test_no_contrast_field(self) -> None:
        snap = build_snapshot("INFP", {"EI": 0.8, "SN": 0.7, "TF": 0.9, "JP": 0.8})
        self.assertIsNotNone(snap)
        assert snap is not None
        self.assertNotIn("contrast", snap)

    def test_invalid_code_degrades(self) -> None:
        self.assertIsNone(build_snapshot("XXXX", RATIOS))

    def test_public_fields_stripped(self) -> None:
        snap = build_snapshot("ESTJ", RATIOS)
        self.assertIsNotNone(snap)
        assert snap is not None
        # 精确分数不暴露给前端
        if snap.get("primary"):
            self.assertNotIn("score", snap["primary"])
        # pool 不应泄漏
        self.assertNotIn("pool", snap)


if __name__ == "__main__":
    unittest.main(verbosity=2)
