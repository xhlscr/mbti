"""输入校验与限流的纯逻辑测试（不依赖数据库/HTTP 服务）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1.endpoints.sessions import _clean_answers  # noqa: E402
from app.core.exceptions import InvalidAnswer  # noqa: E402
from app.schemas import AnswersIn, CreateSessionIn, SubmitIn  # noqa: E402


def build_questions(count: int = 40) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            code=f"q{i:02d}",
            payload={"options": ["a", "b", "c", "d", "e"], "weights": [-2, -1, 0, 1, 2]},
        )
        for i in range(count)
    ]


class SchemaTests(unittest.TestCase):
    def test_valid_answers_pass(self) -> None:
        payload = SubmitIn(answers={f"q{i:02d}": i % 5 for i in range(40)})
        self.assertEqual(len(payload.answers), 40)

    def test_too_many_answers_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AnswersIn(answers={f"q{i:03d}": 0 for i in range(41)})

    def test_index_out_of_range_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AnswersIn(answers={"q00": 5})
        with self.assertRaises(ValidationError):
            AnswersIn(answers={"q00": -1})

    def test_bool_index_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AnswersIn(answers={"q00": True})   # type: ignore[dict-item]

    def test_bank_slug_sanitized(self) -> None:
        with self.assertRaises(ValidationError):
            CreateSessionIn(bank="../etc/passwd")
        self.assertEqual(CreateSessionIn(bank="mbti-v1").bank, "mbti-v1")


class CleanAnswersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.questions = build_questions()

    def test_foreign_code_rejected(self) -> None:
        with self.assertRaises(InvalidAnswer):
            _clean_answers({"not_in_session": 0}, self.questions)  # type: ignore[arg-type]

    def test_out_of_session_count_rejected(self) -> None:
        answers = {f"q{i:02d}": 0 for i in range(40)}
        answers["q99"] = 0
        with self.assertRaises(InvalidAnswer):
            _clean_answers(answers, self.questions[:40])  # type: ignore[arg-type]

    def test_valid_answers_kept(self) -> None:
        cleaned = _clean_answers({"q00": 0, "q01": 4}, self.questions)  # type: ignore[arg-type]
        self.assertEqual(cleaned, {"q00": 0, "q01": 4})


if __name__ == "__main__":
    unittest.main(verbosity=2)
