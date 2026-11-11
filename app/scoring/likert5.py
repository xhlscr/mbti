"""5 级梯度量表：选项权重直接写在 payload 里。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.scoring.registry import register

if TYPE_CHECKING:
    from app.models.question import Question


@register("likert5", cap=lambda q: {q.dim: 2.0})
def score(q: "Question", value: dict) -> dict[str, float]:
    idx = int(value["index"])
    weights = q.payload["weights"]
    if not 0 <= idx < len(weights):
        raise ValueError(f"{q.code}: 选项下标越界 {idx}")
    return {q.dim: float(weights[idx])}
