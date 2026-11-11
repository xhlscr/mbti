"""分层抽题：每个维度抽 `per_dim` 道，按场景标签轮转，避免题目扎堆。"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from app.models.question import Question

DIMS: tuple[str, ...] = ("EI", "SN", "TF", "JP")


def draw(questions: Sequence["Question"], per_dim: int, seed: int) -> list["Question"]:
    """按维度等量抽取，返回打散后的题目列表。

    Raises:
        ValueError: 某一维题目不足 `per_dim`。
    """
    rng = random.Random(seed)
    picked: list["Question"] = []

    for dim in DIMS:
        pool = [q for q in questions if q.dim == dim]
        groups: dict[str, list["Question"]] = defaultdict(list)
        for q in pool:
            # 主场景标签：保证同一轮抽题覆盖不同场景
            groups[q.tags[0] if q.tags else "其他"].append(q)

        buckets = [g[:] for g in groups.values()]
        for bucket in buckets:
            rng.shuffle(bucket)

        out: list["Question"] = []
        i = 0
        while len(out) < per_dim and any(buckets):
            bucket = buckets[i % len(buckets)]
            i += 1
            if bucket:
                out.append(bucket.pop())

        if len(out) < per_dim:
            raise ValueError(f"{dim} 维只有 {len(out)} 题，不足 {per_dim} 道")
        picked.extend(out)

    rng.shuffle(picked)
    return picked
