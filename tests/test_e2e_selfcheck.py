"""端到端自测：用 SQLite 内存库跑抽题→结算→分享结果→重测的完整链路。

用 TestClient 打真实 HTTP，验证前端两个修复点所依赖的后端行为：
1. 每次 POST /sessions 都会用新 seed 抽一套题（重新测试能生成新试题）
2. GET /results/{share_id} 能读到结算快照（分享链接可访问）

生产用 PostgreSQL 的 ARRAY / JSONB；SQLite 无这些类型，这里在测试进程内
注册编译与bind/result处理器把它们降级为 JSON，仅用于自测。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import JSON  # noqa: E402
from sqlalchemy.dialects.postgresql import ARRAY, JSONB  # noqa: E402
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import SQLModel, Session, create_engine  # noqa: E402

# ---- SQLite 方言下把 PG 的 ARRAY / JSONB 当作 JSON 处理 ------------------
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


_SQLITE = sqlite_dialect()
_json = JSON()
_ARRAY_BIND = ARRAY.bind_processor
_ARRAY_RESULT = ARRAY.result_processor


def _array_bind_sqlite(self, dialect):  # noqa: ANN001
    if dialect.name == "sqlite":
        return JSON().bind_processor(dialect)
    return _ARRAY_BIND(self, dialect)


def _array_result_sqlite(self, dialect, coltype):  # noqa: ANN001
    if dialect.name == "sqlite":
        return JSON().result_processor(dialect, coltype)
    return _ARRAY_RESULT(self, dialect, coltype)


ARRAY.bind_processor = _array_bind_sqlite  # type: ignore[method-assign]
ARRAY.result_processor = _array_result_sqlite  # type: ignore[method-assign]

# SQLite 下用字符串主键做 db.get 时，原生 Uuid 处理器要求 .hex；
# 而 HTTP 路径参数就是字符串。这里让处理器兼容 str（PG/psycopg 原生支持）。
from sqlalchemy.types import Uuid as _Uuid  # noqa: E402

_UUID_BIND = _Uuid.bind_processor


def _uuid_bind_sqlite(self, dialect):  # noqa: ANN001
    proc = _UUID_BIND(self, dialect)
    if proc is None or dialect.name != "sqlite":
        return proc

    def coerce(value):  # noqa: ANN001
        if isinstance(value, str):
            import uuid as _uuid

            value = _uuid.UUID(value)
        return proc(value)

    return coerce


_Uuid.bind_processor = _uuid_bind_sqlite  # type: ignore[method-assign]
# -------------------------------------------------------------------------

import app.models  # noqa: E402,F401  注册所有表
from app.api.deps import get_db  # noqa: E402
from app.main import app  # noqa: E402


def set_answer_ids(questions: list[dict]) -> dict[str, int]:
    return {q["id"]: 0 for q in questions}


class EndToEndSelfCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(cls.engine)

        def override_get_db():
            with Session(cls.engine) as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        ARRAY.bind_processor = _ARRAY_BIND  # type: ignore[method-assign]
        ARRAY.result_processor = _ARRAY_RESULT  # type: ignore[method-assign]
        cls.engine.dispose()

    def _create(self) -> dict:
        resp = self.client.post("/api/v1/sessions", json={"bank": "mbti-v1"})
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    def test_share_result_is_readable(self) -> None:
        """结算后分享链接能读到完整快照（type + functions）。"""
        session = self._create()
        answers = set_answer_ids(session["questions"])
        resp = self.client.post(
            f"/api/v1/sessions/{session['session_id']}/submit", json={"answers": answers}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        share_id = resp.json()["share_id"]

        get = self.client.get(f"/api/v1/results/{share_id}")
        self.assertEqual(get.status_code, 200, get.text)
        data = get.json()
        self.assertEqual(data["share_id"], share_id)
        self.assertIn("type", data)
        self.assertIn("functions", data)
        self.assertEqual(len(data["code"]), 4)

    def test_unknown_share_id_returns_404(self) -> None:
        resp = self.client.get("/api/v1/results/doesnotexist")
        self.assertEqual(resp.status_code, 404)

    def test_retake_draws_new_question_set(self) -> None:
        """两次 create_session 生成不同的 session_id 与抽题组合（重新测试）。"""
        first = self._create()
        second = self._create()
        self.assertNotEqual(first["session_id"], second["session_id"])
        first_ids = [q["id"] for q in first["questions"]]
        second_ids = [q["id"] for q in second["questions"]]
        self.assertGreater(len(first_ids), 0)
        self.assertEqual(len(first_ids), len(second_ids))
        self.assertNotEqual(first_ids, second_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
