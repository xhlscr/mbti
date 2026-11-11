"""题型 → 计分策略注册表。

纯 Python，不依赖 Web 框架与 ORM，可单独测试。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # 只在类型检查时引入 ORM，保证本模块可脱离第三方依赖运行
    from app.models.question import Question

ScoreFn = Callable[["Question", dict], dict[str, float]]
CapFn = Callable[["Question"], dict[str, float]]


@dataclass(frozen=True)
class Scorer:
    score: ScoreFn
    cap: CapFn


SCORERS: dict[str, Scorer] = {}


def register(name: str, cap: CapFn):
    """注册一种题型的计分策略。score 与 cap 必须成对提供。"""

    def deco(fn: ScoreFn) -> ScoreFn:
        SCORERS[name] = Scorer(fn, cap)
        return fn

    return deco


def get(name: str) -> Scorer:
    from app.core.exceptions import UnsupportedQuestionType

    if name not in SCORERS:
        raise UnsupportedQuestionType(f"未注册的题型: {name}")
    return SCORERS[name]
