"""内容加载：types.json / functions.json / questions.json。

启动时一次性读进内存，量小（< 60KB），不值得每次请求读盘。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.exceptions import InvalidType

DIMS: tuple[str, ...] = ("EI", "SN", "TF", "JP")
ALL_TYPES: tuple[str, ...] = tuple(a + b + c + d for a in "EI" for b in "SN" for c in "TF" for d in "JP")


def _read(name: str) -> Any:
    path: Path = settings.content_dir / name
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def question_bundle() -> dict:
    data = _read("questions.json")
    if len(data.get("questions", [])) == 0:
        raise RuntimeError("questions.json 为空，先跑 import_content.py")
    return data


@lru_cache(maxsize=1)
def types() -> dict[str, dict]:
    return _read("types.json")


@lru_cache(maxsize=1)
def functions() -> dict[str, dict]:
    return _read("functions.json")


def type_profile(code: str) -> dict[str, Any]:
    code = code.upper()
    if code not in ALL_TYPES:
        raise InvalidType(code)
    profile = dict(types()[code])
    profile["functions"] = functions()[code]
    return profile


def bank_meta(slug: str = "mbti-v1") -> dict[str, Any]:
    bank = question_bundle()["bank"]
    if bank["slug"] != slug:
        from app.core.exceptions import InvalidBank

        raise InvalidBank(slug)
    dims = [
        {"key": d, "left": {"EI": "E", "SN": "S", "TF": "T", "JP": "J"}[d],
         "right": {"EI": "I", "SN": "N", "TF": "F", "JP": "P"}[d]}
        for d in DIMS
    ]
    return {
        "slug": bank["slug"],
        "version": bank["version"],
        "total": bank["per_dim"] * len(DIMS),
        "per_dim": bank["per_dim"],
        "dims": dims,
    }
