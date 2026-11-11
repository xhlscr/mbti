"""名人匹配的回归测试。只依赖标准库，直接跑：

    python -m unittest discover -s api/tests -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.matching.celebrity import (  # noqa: E402
    ALL_TYPES,
    DIMS,
    POLES,
    Celebrity,
    flip_letter,
    infer_type,
    letter_at,
    load_celebrities,
    match_celebrities,
    normalize_user_vector,
    similarity,
    stability_report,
    validate_type,
    vector_from_type,
)

DATA_PATH = API_ROOT / "app" / "data" / "celebrities.json"


def typical_vector(code: str, magnitude: float = 0.7) -> dict[str, float]:
    return vector_from_type(code, magnitude)


class DataIntegrityTests(unittest.TestCase):
    """种子数据本身的健康度。任何一条挂了，前端就会显示错人。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        cls.items = cls.raw["celebrities"]
        cls.pool = load_celebrities(DATA_PATH)

    def test_count_and_coverage(self) -> None:
        self.assertEqual(len(self.items), 64)
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item["type"]] = counts.get(item["type"], 0) + 1
        self.assertEqual(set(counts), set(ALL_TYPES), "16 种类型必须全部覆盖")
        for code, n in counts.items():
            self.assertGreaterEqual(n, 3, f"{code} 的名人不足 3 个，匹配会失去区分度")

    def test_ids_unique_and_slugged(self) -> None:
        ids = [item["id"] for item in self.items]
        self.assertEqual(len(ids), len(set(ids)), "存在重复 id")
        for i in ids:
            self.assertRegex(i, r"^[a-z0-9]+(-[a-z0-9]+)*$", f"id 不是 kebab-case: {i}")

    def test_vector_keys_complete(self) -> None:
        for item in self.items:
            self.assertEqual(set(item["vector"]), set(DIMS), f"{item['id']} 维度缺失")

    def test_vector_range_and_sign(self) -> None:
        """这是最容易写错的一条：向量符号必须和类型字母一致。"""
        for item in self.items:
            code = item["type"]
            for i, dim in enumerate(DIMS):
                v = item["vector"][dim]
                self.assertLessEqual(abs(v), 1.0, f"{item['id']} {dim} 超出 [-1,1]")
                self.assertGreaterEqual(abs(v), 0.15, f"{item['id']} {dim} 强度过弱，符号不稳定")
                want = -1 if code[i] == POLES[dim][0] else 1
                self.assertEqual(
                    (v > 0) - (v < 0),
                    want,
                    f"{item['id']} 的 {dim}={v} 与类型 {code[i]} 矛盾",
                )

    def test_confidence_and_basis(self) -> None:
        for item in self.items:
            self.assertGreaterEqual(item["confidence"], 0.0)
            self.assertLessEqual(item["confidence"], 1.0)
            self.assertIn(item["basis"], {"documented", "inferred", "disputed"})

    def test_content_not_empty(self) -> None:
        for item in self.items:
            self.assertTrue(item["name"].strip(), f"{item['id']} 没有名字")
            self.assertGreater(len(item.get("why", "")), 8, f"{item['id']} 缺少 why 文案")
            self.assertGreaterEqual(len(item.get("traits", [])), 2, f"{item['id']} traits 过少")
            self.assertIn("license", item.get("portrait", {}), f"{item['id']} 缺少肖像授权字段")

    def test_disputed_have_note(self) -> None:
        for item in self.items:
            if item["basis"] == "disputed":
                self.assertTrue(item.get("note"), f"{item['id']} 标记为 disputed 但没写争议说明")


class PrimitiveTests(unittest.TestCase):
    def test_validate_type(self) -> None:
        self.assertEqual(validate_type("intj"), "INTJ")
        for bad in ("", "XXXX", "INT", "INTJJ", None):
            with self.assertRaises(ValueError):
                validate_type(bad)  # type: ignore[arg-type]

    def test_letter_and_flip(self) -> None:
        self.assertEqual(letter_at("INTJ", "EI"), "I")
        self.assertEqual(letter_at("INTJ", "JP"), "J")
        self.assertEqual(flip_letter("INTJ", "SN"), "ISTJ")
        self.assertEqual(flip_letter(flip_letter("ENFP", "TF"), "TF"), "ENFP")

    def test_infer_type_zero_defaults_left(self) -> None:
        vec = {"EI": 0.0, "SN": 0.5, "TF": -0.5, "JP": 0.0}
        self.assertEqual(infer_type(vec), "ENTJ")

    def test_normalize_fills_and_fixes(self) -> None:
        vec, notes = normalize_user_vector({"SN": 0.8, "TF": 0.9}, "INTJ")
        self.assertEqual(vec["EI"], 0.6)           # 缺失 → 按类型 I 补 +0.6
        self.assertEqual(vec["TF"], -0.9)          # 符号与 T 矛盾 → 翻转
        self.assertTrue(any("TF" in n for n in notes))

    def test_similarity_bounds(self) -> None:
        target = Celebrity(id="x", name="X", type="INTJ", vector=typical_vector("INTJ"),
                           confidence=1.0)
        same = typical_vector("INTJ")
        far = vector_from_type("ESFP")
        self.assertGreater(similarity(same, "INTJ", target), 0.95)
        self.assertLess(similarity(far, "ESFP", target), 0.45)


class MatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pool = load_celebrities(DATA_PATH)

    def test_every_type_gets_same_type_primary(self) -> None:
        for code in ALL_TYPES:
            result = match_celebrities(typical_vector(code), code, self.pool)
            self.assertTrue(result["primary"], f"{code} 没匹配出结果")
            self.assertEqual(
                result["primary"]["type"],
                code,
                f"{code} 匹配到了 {result['primary']['type']}，同型加成没生效",
            )

    def test_no_duplicate_across_slots(self) -> None:
        result = match_celebrities(typical_vector("INTJ"), "INTJ", self.pool)
        ids = [result["primary"]["id"]] + [x["id"] for x in result["also"]]
        if result["contrast"]:
            ids.append(result["contrast"]["id"])
        self.assertEqual(len(ids), len(set(ids)), "同一个人被放进了多个位置")

    def test_scores_are_monotonic(self) -> None:
        result = match_celebrities(typical_vector("ENFP", 0.85), "ENFP", self.pool)
        scores = [result["primary"]["score"]] + [x["score"] for x in result["also"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_deterministic(self) -> None:
        vec = {"EI": 0.31, "SN": 0.62, "TF": -0.44, "JP": 0.77}
        a = match_celebrities(vec, "INTP", self.pool)
        b = match_celebrities(vec, "INTP", self.pool)
        self.assertEqual(a, b, "同样的输入必须给出同样的输出")

    def test_contrast_is_one_letter_away(self) -> None:
        fresh = load_celebrities(DATA_PATH)
        for code in ("INTJ", "ENFP", "ISFJ", "ESTP"):
            result = match_celebrities(typical_vector(code), code, fresh)
            contrast = result["contrast"]
            self.assertIsNotNone(contrast, f"{code} 没有选出反差位")
            diff = sum(1 for a, b in zip(contrast["type"], code) if a != b)
            self.assertEqual(diff, 1, f"{code} 的反差位 {contrast['type']} 差得太多，不够'聚焦'")

    def test_contrast_on_mild_user_may_be_none(self) -> None:
        """反差位是可选内容：给一个没有任何极端的用户，允许没有反差位。"""
        vec = {"EI": 0.0, "SN": 0.0, "TF": 0.0, "JP": 0.0}
        result = match_celebrities(vec, "INFP", self.pool, include_contrast=False)
        self.assertIsNone(result["contrast"])
        self.assertTrue(result["primary"])

    def test_exclude_ids(self) -> None:
        first = match_celebrities(typical_vector("INFJ"), "INFJ", self.pool)
        second = match_celebrities(
            typical_vector("INFJ"), "INFJ", self.pool,
            exclude_ids=[first["primary"]["id"]],
        )
        self.assertNotEqual(first["primary"]["id"], second["primary"]["id"])

    def test_spread_and_runner_up(self) -> None:
        base = Celebrity(id="a", name="A", type="INTJ", vector=typical_vector("INTJ"),
                         confidence=0.5)
        twin = Celebrity(id="b", name="B", type="INTJ", vector=typical_vector("INTJ"),
                         confidence=0.5)
        result = match_celebrities(typical_vector("INTJ"), "INTJ", [base, twin])
        self.assertLess(result["spread"], 1e-6, "两个完全相同的候选，分差应为 0")
        self.assertEqual(result["runner_up"], "b")

    def test_low_confidence_ranks_lower(self) -> None:
        vec = {"EI": 0.8, "SN": 0.8, "TF": -0.8, "JP": 0.8}
        sure = Celebrity(id="sure", name="Sure", type="INTP", vector=typical_vector("INTP"),
                         confidence=0.9)
        vague = Celebrity(id="vague", name="Vague", type="INTP", vector=typical_vector("INTP"),
                          confidence=0.2)
        result = match_celebrities(vec, "INTP", [vague, sure])
        self.assertEqual(result["primary"]["id"], "sure")

    def test_empty_pool_raises(self) -> None:
        with self.assertRaises(ValueError):
            match_celebrities(typical_vector("INTJ"), "INTJ", [])

    def test_missing_both_inputs_raises(self) -> None:
        with self.assertRaises(ValueError):
            match_celebrities(None, None, self.pool)

    def test_explain_mentions_aligned_dimension(self) -> None:
        result = match_celebrities(typical_vector("INTJ"), "INTJ", self.pool)
        notes = result["primary"]["match_notes"]
        self.assertTrue(notes)
        self.assertTrue(any(DIM_NAME in n for n in notes for DIM_NAME in ("精力方向", "信息获取", "决策方式", "生活态度")))

    def test_same_set_reproduces_same_celebrities(self) -> None:
        """重测时题目不同、答案有 ±1 档波动，展示给用户的那一小撮人不该换。

        注意断言的是「集合稳定」而不是「第一名稳定」：同型内部（比如诸葛亮 vs 牛顿）
        顺序互换是无害的，因为页面按档位展示、不公布排名；真正要守的是
        「用户不会发现上次那批人整体消失了」。
        """
        vec = {"EI": 0.72, "SN": 0.86, "TF": -0.41, "JP": -0.78}
        report = stability_report(vec, "INTJ", self.pool, jitter=0.10, trials=200)
        self.assertGreaterEqual(report["top3_overlap"], 0.95, report)
        self.assertGreaterEqual(report["primary_stability"], 0.65, report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
