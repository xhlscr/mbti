"""二选一强制选择题型。

第一阶段只用它验证"加题型不用改答题流程"，配 2 道 fixture 题即可。
payload:
    { "options": ["A 说法", "B 说法"],
      "deltas": [{ "EI": -2 }, { "EI": 2 }] }
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.scoring.registry import register

if TYPE_CHECKING:
    from app.models.question import Question


def _cap(q: "Question") -> dict[str, float]:
    dims = q.payload["deltas"][0].keys()
    return {d: max(abs(opt.get(d, 0.0)) for opt in q.payload["deltas"]) for d in dims}


@register("choice2", cap=_cap)
def score(q: "Question", value: dict) -> dict[str, float]:
    idx = int(value["index"])
    deltas = q.payload["deltas"]
    if not 0 <= idx < len(deltas):
        raise ValueError(f"{q.code}: 选项下标越界 {idx}")
    return {k: float(v) for k, v in deltas[idx].items()}
