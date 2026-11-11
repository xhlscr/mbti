"""聚合层：把每题的带符号增量汇总成四维比率与类型码。"""

from __future__ import annotations

from typing import Mapping, Sequence, TYPE_CHECKING

from app.scoring import get

if TYPE_CHECKING:
    from app.models.question import Question

DIMS: tuple[str, ...] = ("EI", "SN", "TF", "JP")
POLES: dict[str, tuple[str, str]] = {
    "EI": ("E", "I"),
    "SN": ("S", "N"),
    "TF": ("T", "F"),
    "JP": ("J", "P"),
}


def aggregate(
    answers: Mapping[int, dict],
    questions: Mapping[int, "Question"],
) -> tuple[str, dict[str, float]]:
    """返回 (类型码, 四维比率)。

    比率 = 该维累计增量 / 该维累计上限，取值 [-1, 1]；
    负数偏左极（E/S/T/J），正数偏右极（I/N/F/P），0 按规则取左极。
    """
    acc = dict.fromkeys(DIMS, 0.0)
    cap = dict.fromkeys(DIMS, 0.0)

    for qid, value in answers.items():
        q = questions.get(qid)
        if q is None:
            continue
        scorer = get(q.type)
        for dim, delta in scorer.score(q, value).items():
            acc[dim] += delta
        for dim, max_abs in scorer.cap(q).items():
            cap[dim] += abs(max_abs)

    ratios = {d: (acc[d] / cap[d] if cap[d] else 0.0) for d in DIMS}
    code = "".join(POLES[d][1] if ratios[d] > 0 else POLES[d][0] for d in DIMS)
    return code, ratios


def strength(ratio: float) -> int:
    """展示用强度：50% 表示完全均衡，100% 表示完全一边倒。"""
    return round(50 + abs(ratio) * 50)
