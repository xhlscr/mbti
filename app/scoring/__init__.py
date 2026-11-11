"""计分策略包。

每种题型注册一个 `Scorer(score, cap)`：
- `score(q, value)` → `{dim: 带符号增量}`，负=左极(E/S/T/J)
- `cap(q)`          → `{dim: 该题在该维的最大贡献}`，用于归一化
"""

from app.scoring.registry import SCORERS, Scorer, get, register

# 导入即注册；新增题型只需在这里加一行 import
from app.scoring import choice2, likert5  # noqa: E402,F401

__all__ = ["SCORERS", "Scorer", "get", "register"]
