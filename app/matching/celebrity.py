"""历史名人匹配核心算法。

设计要点（对应 README 里的「为什么这么做」）：

1. **纯函数、零第三方依赖**，可以直接被 FastAPI 路由、CLI、测试复用。
2. **不用 4 个字母查表**，用四维带符号向量算距离，这样同型的人也能得到不同结果。
3. **三档呈现**（最像 / 也很像 / 反差位），不公布排名，避免"上次像鲁迅这次像尼采"。
4. **争议降权**：confidence 直接乘进相似度，推断越不确定的人越靠后。
5. **稳定性可量化**：`stability_report()` 可以对任意用户向量做抖动测试，用来调参。

向量约定：负值 = 左极（E / S / T / J），正值 = 右极（I / N / F / P），
绝对值表示强度，取值 [-1, 1]。
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field as dc_field
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DIMS: tuple[str, ...] = ("EI", "SN", "TF", "JP")

POLES: dict[str, tuple[str, str]] = {
    "EI": ("E", "I"),
    "SN": ("S", "N"),
    "TF": ("T", "F"),
    "JP": ("J", "P"),
}

DIM_LABEL: dict[str, str] = {
    "EI": "精力方向",
    "SN": "信息获取",
    "TF": "决策方式",
    "JP": "生活态度",
}

POLE_LABEL: dict[str, str] = {
    "E": "外倾", "I": "内倾",
    "S": "感觉", "N": "直觉",
    "T": "思考", "F": "情感",
    "J": "判断", "P": "知觉",
}

# S/N 的区分度最高，权重略高；其余等权。改这里即可调整"哪一维更决定像不像"。
WEIGHTS: dict[str, float] = {"EI": 1.0, "SN": 1.2, "TF": 1.0, "JP": 1.0}

ALL_TYPES: tuple[str, ...] = tuple(
    "".join(poles) for poles in product(*(POLES[d] for d in DIMS))
)

TYPE_BONUS = 0.08          # 同型加成：同型优先，但不绝对
CONF_FLOOR = 0.85          # 置信度对分数的最大惩罚比例（conf=0 时打 85 折）
MIN_ABS = 0.15             # 向量绝对值下限，避免符号判定不稳
ALSO_MIN = 0.55            # "也很像"档的绝对下限
DEFAULT_MAGNITUDE = 0.6    # 只给了类型、没给强度时的默认强度


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Celebrity:
    """一条名人记录。字段与 celebrities.json 一一对应。"""

    id: str
    name: str
    type: str
    vector: dict[str, float]
    confidence: float = 0.5
    basis: str = "inferred"
    alias: str = ""
    era: str = ""
    region: str = ""
    field: str = ""
    traits: tuple[str, ...] = ()
    why: str = ""
    quote: str = ""
    quote_source: str = ""
    note: str = ""
    portrait: dict[str, Any] = dc_field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Celebrity":
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            type=str(raw["type"]).upper(),
            vector={d: float(raw["vector"][d]) for d in DIMS},
            confidence=float(raw.get("confidence", 0.5)),
            basis=str(raw.get("basis", "inferred")),
            alias=str(raw.get("alias", "")),
            era=str(raw.get("era", "")),
            region=str(raw.get("region", "")),
            field=str(raw.get("field", "")),
            traits=tuple(raw.get("traits", ())),
            why=str(raw.get("why", "")),
            quote=str(raw.get("quote", "")),
            quote_source=str(raw.get("quote_source", "")),
            note=str(raw.get("note", "")),
            portrait=dict(raw.get("portrait", {})),
        )


@dataclass(frozen=True, slots=True)
class Scored:
    """中间结果：一个候选 + 它的分数。"""

    celebrity: Celebrity
    score: float


def coerce_candidate(obj: "Celebrity | Mapping[str, Any]") -> Celebrity:
    return obj if isinstance(obj, Celebrity) else Celebrity.from_dict(obj)


# ---------------------------------------------------------------------------
# 向量与类型码的基础工具
# ---------------------------------------------------------------------------


def validate_type(code: str) -> str:
    """校验并规范化类型码，非法直接抛错（宁可炸，也别算出个 INTP 的孪生兄弟）。"""
    code = (code or "").strip().upper()
    if code not in ALL_TYPES:
        raise ValueError(f"非法 MBTI 类型码: {code!r}，合法值见 ALL_TYPES")
    return code


def letter_at(code: str, dim: str) -> str:
    """取出类型码在某一维上的字母。"""
    return validate_type(code)[DIMS.index(dim)]


def pole_sign(letter: str, dim: str) -> int:
    """字母 → 向量符号：左极 -1，右极 +1。"""
    return -1 if letter == POLES[dim][0] else 1


def vector_from_type(code: str, magnitude: float = DEFAULT_MAGNITUDE) -> dict[str, float]:
    """只知类型时，构造一个"典型强度"向量。"""
    code = validate_type(code)
    return {d: pole_sign(code[DIMS.index(d)], d) * magnitude for d in DIMS}


def infer_type(vec: Mapping[str, float]) -> str:
    """从向量反推类型码；某维为 0 时按题库规则默认取左极。"""
    letters = []
    for d in DIMS:
        v = float(vec.get(d, 0.0))
        letters.append(POLES[d][0] if v <= 0 else POLES[d][1])
    return "".join(letters)


def flip_letter(code: str, dim: str) -> str:
    """把某一维的字母翻到另一极，其余保持不变。"""
    code = validate_type(code)
    i = DIMS.index(dim)
    left, right = POLES[dim]
    flipped = right if code[i] == left else left
    return code[:i] + flipped + code[i + 1 :]


def normalize_user_vector(
    raw: Mapping[str, float] | None,
    user_type: str,
) -> tuple[dict[str, float], list[str]]:
    """把用户向量补齐、钳制、并与类型码对齐。

    - 缺维度：按类型方向补 0.6
    - 超范围：钳到 [-1, 1]
    - 符号与类型矛盾：以类型为准，翻转符号并记录一条 note
    """
    user_type = validate_type(user_type)
    vec: dict[str, float] = {}
    notes: list[str] = []

    for i, d in enumerate(DIMS):
        raw_v = None if raw is None else raw.get(d)
        want_sign = pole_sign(user_type[i], d)

        if raw_v is None:
            vec[d] = want_sign * DEFAULT_MAGNITUDE
            notes.append(f"{d}: 未提供，按类型补 {vec[d]:+.2f}")
            continue

        v = float(raw_v)
        if not math.isfinite(v):
            vec[d] = want_sign * DEFAULT_MAGNITUDE
            notes.append(f"{d}: 非有限值，按类型补 {vec[d]:+.2f}")
            continue

        v = max(-1.0, min(1.0, v))
        if abs(v) < MIN_ABS:
            # 接近均衡：方向沿用类型，强度提到下限，避免后续除零/抖动
            vec[d] = want_sign * MIN_ABS
            notes.append(f"{d}: 接近均衡（{v:+.2f}），按类型方向取 {vec[d]:+.2f}")
            continue

        if (v > 0) != (want_sign > 0):
            notes.append(f"{d}: 向量符号与类型 {user_type[i]} 矛盾，已按类型翻转")
        vec[d] = abs(v) * want_sign

    return vec, notes


# ---------------------------------------------------------------------------
# 相似度
# ---------------------------------------------------------------------------


def agreement(
    user_vec: Mapping[str, float],
    cand: Celebrity,
) -> float:
    """四维加权一致度 ∈ [0, 1]。

    每一维单独算"有多接近"（差值 0 → 1.0，差值 2 即完全反向 → 0.0），
    再按权重取平均。相比欧氏距离，它的好处是刻度直观：
    四维里三同一反 ≈ 0.8，两同两反 ≈ 0.6，全反 = 0。
    """
    wsum = sum(WEIGHTS.values())
    total = 0.0
    for d in DIMS:
        delta = min(abs(user_vec[d] - cand.vector[d]), 2.0)
        total += WEIGHTS[d] * (1.0 - delta / 2.0)
    return total / wsum


def similarity(
    user_vec: Mapping[str, float],
    user_type: str,
    cand: Celebrity,
) -> float:
    """归一化相似度 ∈ [0, 1]，同型加成 + 置信度降权。

    标定后的大致刻度：
    - 完全重合 1.00
    - 同型、取向接近 0.90–0.97
    - 差一个字母 0.75–0.85
    - 差两个字母 0.55–0.70
    - 四维全反 0
    """
    base = agreement(user_vec, cand)
    if cand.type == user_type:
        base += TYPE_BONUS
    base = max(0.0, min(1.0, base))
    conf_factor = CONF_FLOOR + (1.0 - CONF_FLOOR) * max(0.0, min(1.0, cand.confidence))
    return base * conf_factor


# ---------------------------------------------------------------------------
# 匹配主函数
# ---------------------------------------------------------------------------


def match_celebrities(
    user_vector: Mapping[str, float] | None = None,
    user_type: str | None = None,
    candidates: Sequence[Celebrity | Mapping[str, Any]] = (),
    *,
    also_limit: int = 2,
    include_contrast: bool = True,
    min_contrast_score: float = 0.50,
    exclude_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """核心入口。返回可直接 JSON 序列化的 dict。

    Args:
        user_vector: 四维带符号向量，缺失的维度按类型补默认值。
        user_type: 四字母类型码；不传则由向量反推。
        candidates: Celebrity 或 celebrities.json 里的 dict 列表。
        also_limit: "也很像"最多给几个人。
        include_contrast: 是否挑选"反差位"。
        min_contrast_score: 反差位的相似度下限，太低则不给。
        exclude_ids: 需要排除的 id（例如详情页要"换一个"时传当前 id）。

    Returns:
        {
          "type": "INTJ",
          "vector": {...},
          "primary": {...} | None,
          "also": [...],
          "contrast": {...} | None,
          "spread": float,         # 第一与第二的分差，通常很小，别当排名用
          "runner_up": str | None,
          "pool": {"size": int, "per_type": {...}},
          "notes": [...],          # 向量归一化时的修正记录
        }
    """
    excluded = {str(i) for i in exclude_ids}
    pool = [coerce_candidate(c) for c in candidates]
    pool = [c for c in pool if c.id not in excluded]

    if not pool:
        raise ValueError("候选池为空：检查 celebrities.json 是否加载成功、exclude_ids 是否过滤过度")

    if user_type is None:
        if user_vector is None:
            raise ValueError("user_type 与 user_vector 至少提供一个")
        user_type = infer_type(user_vector)
    user_type = validate_type(user_type)

    vec, notes = normalize_user_vector(user_vector, user_type)

    scored = sorted(
        (Scored(c, similarity(vec, user_type, c)) for c in pool),
        key=lambda s: (-s.score, -s.celebrity.confidence, s.celebrity.id),
    )

    best = scored[0]
    used = {best.celebrity.id}

    also = [
        s for s in scored[1:] if s.score >= ALSO_MIN and s.celebrity.id not in used
    ][: max(0, also_limit)]
    used.update(s.celebrity.id for s in also)

    contrast = None
    contrast_reason = ""
    if include_contrast:
        contrast, contrast_reason = _pick_contrast(
            vec, user_type, scored, used, min_contrast_score
        )

    runner_up = scored[1].celebrity.id if len(scored) > 1 else None
    spread = (best.score - scored[1].score) if len(scored) > 1 else 1.0

    return {
        "type": user_type,
        "vector": {d: round(vec[d], 4) for d in DIMS},
        "primary": _public(best, vec, user_type),
        "also": [_public(s, vec, user_type) for s in also],
        "contrast": _public(contrast, vec, user_type) if contrast else None,
        "contrast_reason": contrast_reason,
        # 第一名与第二名的分差。注意：同型内部这个值通常很小（0.00–0.05），
        # 因为历史人物的向量本身就是估计值，精度支撑不了"诸葛亮比牛顿更像你 0.7%"
        # 这种结论。前端应当把 primary + also 当作一组展示，而不是排名。
        "spread": round(spread, 4),
        "runner_up": runner_up,
        "pool": {
            "size": len(pool),
            "per_type": _count_types(pool),
        },
        "notes": notes,
    }


def _count_types(pool: Sequence[Celebrity]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in pool:
        counts[c.type] = counts.get(c.type, 0) + 1
    return dict(sorted(counts.items()))


def _pick_contrast(
    user_vec: Mapping[str, float],
    user_type: str,
    scored: Sequence[Scored],
    used: set[str],
    min_score: float,
) -> tuple[Scored | None, str]:
    """挑一位"反差位"：在你最强的那一维上与你相反，其余三维尽量相同。

    这个规则的好处是差异**聚焦**——不是"完全相反的人"，而是"只差这一点的人"，
    解释起来一句话就能说清，也不会让用户觉得被冒犯。
    """
    strongest = max(DIMS, key=lambda d: abs(user_vec[d]))
    target_type = flip_letter(user_type, strongest)
    label = DIM_LABEL[strongest]

    def usable(s: Scored) -> bool:
        return s.celebrity.id not in used and s.score >= min_score

    exact = [s for s in scored if usable(s) and s.celebrity.type == target_type]
    if exact:
        pick = exact[0]
        return pick, f"你在「{label}」上最强，TA 恰好在这唯一一维上与你相反"

    # 退化：没有恰好差一个字母的人，就找该维度上确实相反、且总体尽量接近的
    want = -1 if user_vec[strongest] > 0 else 1
    relaxed = [
        s
        for s in scored
        if usable(s)
        and s.celebrity.type != user_type
        and (1 if s.celebrity.vector[strongest] > 0 else -1) == want
    ]
    if not relaxed:
        return None, ""

    def key(s: Scored) -> tuple[int, float]:
        shared = sum(
            1
            for d in DIMS
            if d != strongest and letter_at(s.celebrity.type, d) == letter_at(user_type, d)
        )
        return (shared, s.score)

    pick = max(relaxed, key=key)
    return pick, f"TA 在「{label}」上与你方向相反，但整体气质仍与你相近"


def _public(scored: Scored, user_vec: Mapping[str, float], user_type: str) -> dict[str, Any]:
    """把内部结构摊平成前端直接可用的形状。"""
    c = scored.celebrity
    return {
        "id": c.id,
        "name": c.name,
        "alias": c.alias,
        "type": c.type,
        "era": c.era,
        "region": c.region,
        "field": c.field,
        "traits": list(c.traits),
        "why": c.why,
        "quote": c.quote,
        "quote_source": c.quote_source,
        "note": c.note,
        "portrait": c.portrait,
        "basis": c.basis,
        "confidence": round(c.confidence, 2),
        "score": round(scored.score, 4),
        "percent": int(round(scored.score * 100)),
        "same_type": c.type == user_type,
        "match_notes": explain_match(user_vec, user_type, c),
    }


# ---------------------------------------------------------------------------
# 解释文案
# ---------------------------------------------------------------------------


def explain_match(
    user_vec: Mapping[str, float],
    user_type: str,
    cand: Celebrity,
    *,
    limit: int = 2,
) -> list[str]:
    """生成 1-2 句"为什么像"的结构化说明。

    只依赖向量，不调模型——保证零成本、零延迟、可复现。
    """
    diffs = {d: cand.vector[d] - user_vec[d] for d in DIMS}
    gaps = {d: abs(diffs[d]) for d in DIMS}

    aligned = min(DIMS, key=lambda d: gaps[d])
    divergent = max(DIMS, key=lambda d: gaps[d])

    out: list[str] = []

    if gaps[aligned] <= 0.25:
        pole = POLES[aligned][0] if user_vec[aligned] < 0 else POLES[aligned][1]
        out.append(
            f"「{DIM_LABEL[aligned]}」上你们几乎重合："
            f"你偏 {pole}（{POLE_LABEL[pole]}，强度 {abs(user_vec[aligned]):.2f}），"
            f"TA 也是同样的方向。"
        )

    if gaps[divergent] > 0.35 and len(out) < limit:
        your_pole = POLES[divergent][0] if user_vec[divergent] < 0 else POLES[divergent][1]
        their_pole = POLES[divergent][0] if cand.vector[divergent] < 0 else POLES[divergent][1]
        out.append(
            f"最不像的一处是「{DIM_LABEL[divergent]}」："
            f"你偏 {your_pole}（{POLE_LABEL[your_pole]}），TA 偏 {their_pole}（{POLE_LABEL[their_pole]}）。"
        )

    if not out:
        out.append("四维走向高度一致，属于同一套思维方式的不同强度版本。")

    return out[:limit]


# ---------------------------------------------------------------------------
# 稳定性评估（重测波动）
# ---------------------------------------------------------------------------


def stability_report(
    user_vector: Mapping[str, float],
    user_type: str,
    candidates: Sequence[Celebrity | Mapping[str, Any]],
    *,
    jitter: float = 0.10,
    trials: int = 200,
    seed: int = 7,
) -> dict[str, Any]:
    """在用户向量上叠加 ±jitter 噪声，看第一名是否稳定。

    用来回答产品问题："用户重测一次，名人会不会换人？"

    解读方式：
    - `top3_overlap` 是**关键指标**：用户实际看到的是"1 主 + 2 副"这一组，
      只要这组不整体更换，体验就是稳定的；
    - `primary_stability` 会明显偏低（同型内的前两名顺序互换，例如诸葛亮 vs 牛顿），
      这是正常的、也是无害的——页面按档位展示，不公布排名。

    参考：种子数据下 INTJ 极端用户 jitter=0.10 时约为 0.78 / 1.00。
    `top3_overlap < 0.95` 才说明名人池在同型内太挤，需要补充向量差异更大的名人。
    """
    pool = [coerce_candidate(c) for c in candidates]
    base = match_celebrities(user_vector, user_type, pool)
    base_id = base["primary"]["id"] if base["primary"] else None
    base_top3 = {base["primary"]["id"]} if base["primary"] else set()
    base_top3.update(x["id"] for x in base["also"])

    rng = random.Random(seed)
    hits = 0
    overlaps = 0

    for _ in range(trials):
        noisy = {
            d: max(-1.0, min(1.0, float(user_vector[d]) + rng.uniform(-jitter, jitter)))
            for d in DIMS
        }
        r = match_celebrities(noisy, user_type, pool)
        if r["primary"] and r["primary"]["id"] == base_id:
            hits += 1
        top3 = {x["id"] for x in ([r["primary"]] if r["primary"] else []) + r["also"]}
        if top3 & base_top3:
            overlaps += 1

    return {
        "primary": base_id,
        "primary_stability": round(hits / trials, 4),
        "top3_overlap": round(overlaps / trials, 4),
        "trials": trials,
        "jitter": jitter,
    }


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------


DEFAULT_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "celebrities.json"


def load_celebrities(path: str | Path | None = None) -> list[Celebrity]:
    """读取 celebrities.json，返回 Celebrity 列表。"""
    p = Path(path) if path else DEFAULT_DATA_PATH
    with p.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    items = raw["celebrities"] if isinstance(raw, Mapping) else raw
    return [Celebrity.from_dict(item) for item in items]


__all__ = [
    "ALL_TYPES",
    "Celebrity",
    "DIMS",
    "DIM_LABEL",
    "POLES",
    "POLE_LABEL",
    "Scored",
    "agreement",
    "coerce_candidate",
    "explain_match",
    "flip_letter",
    "infer_type",
    "letter_at",
    "load_celebrities",
    "match_celebrities",
    "normalize_user_vector",
    "pole_sign",
    "similarity",
    "stability_report",
    "validate_type",
    "vector_from_type",
]
