#!/usr/bin/env python3
"""m:n 句对齐（2026-07-30，M2）：Gale-Church 风格的动态规划算法，允许
1:1 / 1:2 / 2:1 / 2:2 / 1:0 / 0:1 合并，不再要求三侧句数严格相等。

方法：把 src 当锚点，分别对 (src, ref) 和 (src, hyp) 各跑一次独立的
Gale-Church 对齐（基于字符数长度的正态分布代价模型），得到 src 的分组
边界；再用这两组对齐关系合并出最终的 (src块, ref块, hyp块) 三元组。
不做真正的三方联合对齐（NP-hard），但避免了要求三侧独立切分后计数
恰好相等这个过严的条件。

用法：
    python3 z5_mn_align.py --lang fr --input outputs/eval/xxx/xxx_hyp.jsonl \
        --semicolon-boundary --output outputs/eval/xxx/xxx_mn_pairs.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluation.sentence_split import split_auto

# Gale-Church 参数：c = 期望的「b 侧字符数 / a 侧字符数」比例，s2 为方差常数。
#
# 2026-07-31（A 步）：`_C` 原为硬编码 1.0，即假设两侧字符数**相等**。这是
# Gale-Church 原论文按英法（两个拉丁语言、字节数可比）标定出来的常数，
# 直接沿用到「任意语言 → 中文」上是错的：本项目七个语向的参考/源文字符数比
# 实测全部落在 0.244~0.321 之间（en 0.294 / ru 0.279 / fr 0.262 / de 0.244 /
# th 0.321 / ar 0.283 / es 0.247），中文用汉字表意，字符数天然只有拉丁/西里尔
# 源文的四分之一上下。用 c=1.0 意味着代价函数系统性地偏好「把 3~4 个中文句子
# 塞给 1 个源文句子」，m:n 块的边界整体漂移，配出来的是**错位的**句对。
#
# 这是本项目"把拉丁书写惯例当成全语种通用规律"的第九次同型 bug。
#
# 修法：不引入按语言硬编码的 c 表（那等于给每个语向单开口径），而是**每次对齐
# 调用内部按两侧总字符数自标定** c = sum(len(b)) / sum(len(a))。自标定对七个
# 语向是同一条规则，且对未来新增语向自动成立。
_C_FALLBACK = 1.0
_S2 = 6.8
_ALIGN_TYPES = [(1, 1), (1, 0), (0, 1), (1, 2), (2, 1), (2, 2)]
_PRIORS = {(1, 1): 0.89, (1, 0): 0.01, (0, 1): 0.01, (1, 2): 0.045, (2, 1): 0.045, (2, 2): 0.01}


def _len(units: list[str], i: int, j: int) -> int:
    return sum(len(u) for u in units[i:j])


def estimate_c(a_units: list[str], b_units: list[str]) -> float:
    """按两侧总字符数自标定长度比 c。两侧任一为空时回落到 1.0。"""
    la = sum(len(u) for u in a_units)
    lb = sum(len(u) for u in b_units)
    if la <= 0 or lb <= 0:
        return _C_FALLBACK
    return lb / la


def _cost(la: int, lb: int, align_type: tuple[int, int], c: float) -> float:
    if la == 0 and lb == 0:
        return 0.0
    # lb 先按 c 折算回 a 侧的尺度，再和 la 比较；mean 同样用折算后的尺度，
    # 否则中文侧字符数小会让 mean 偏小、把 delta 人为放大。
    lb_scaled = lb / c if c > 0 else lb
    mean = (la + lb_scaled) / 2 or 1
    delta = (la - lb_scaled) / math.sqrt(_S2 * mean)
    penalty = abs(delta)
    prior = _PRIORS.get(align_type, 0.001)
    return penalty - math.log(prior)


def gale_church_align(a_units: list[str], b_units: list[str]) -> list[tuple[list[int], list[int]]]:
    """返回 [(a侧句子下标列表, b侧句子下标列表), ...] 的对齐块序列。"""
    n, m = len(a_units), len(b_units)
    c = estimate_c(a_units, b_units)
    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    back: dict[tuple[int, int], tuple[int, int]] = {}
    for i in range(n + 1):
        for j in range(m + 1):
            if dp[i][j] == INF:
                continue
            for da, db in _ALIGN_TYPES:
                ni, nj = i + da, j + db
                if ni > n or nj > m:
                    continue
                la = _len(a_units, i, ni)
                lb = _len(b_units, j, nj)
                cand = dp[i][j] + _cost(la, lb, (da, db), c)
                if cand < dp[ni][nj]:
                    dp[ni][nj] = cand
                    back[(ni, nj)] = (i, j)
    # 回溯
    blocks: list[tuple[list[int], list[int]]] = []
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj = back[(i, j)]
        blocks.append((list(range(pi, i)), list(range(pj, j))))
        i, j = pi, pj
    blocks.reverse()
    return blocks


def align_three_way(src_text: str, ref_text: str, hyp_text: str, semicolon: bool = False) -> list[dict[str, Any]]:
    src_s = split_auto(src_text, semicolon_is_boundary=semicolon)
    ref_s = split_auto(ref_text, semicolon_is_boundary=semicolon)
    hyp_s = split_auto(hyp_text, semicolon_is_boundary=semicolon)
    if not src_s or not ref_s or not hyp_s:
        return [{"source_text": src_text, "ref_text": ref_text, "hypothesis": hyp_text, "block_type": "fallback_whole"}]

    src_ref_blocks = gale_church_align(src_s, ref_s)
    src_hyp_blocks = gale_church_align(src_s, hyp_s)

    # 用 src 侧下标做锚点合并：src_ref_blocks 与 src_hyp_blocks 的 src 分段
    # 边界通常不同，取两者的"并集切点"重新切一遍，保证三侧同步。
    raw_cuts = {b[0][-1] + 1 if b[0] else None for b in src_ref_blocks} | {b[0][-1] + 1 if b[0] else None for b in src_hyp_blocks}
    cut_points = sorted(c for c in raw_cuts if c is not None)
    if not cut_points or cut_points[-1] != len(src_s):
        cut_points.append(len(src_s))

    def ref_range_for_src(lo: int, hi: int) -> tuple[int, int]:
        lo_r = hi_r = None
        for sidx, ridx in src_ref_blocks:
            if sidx and sidx[0] >= lo and sidx[-1] < hi:
                if ridx:
                    lo_r = ridx[0] if lo_r is None else min(lo_r, ridx[0])
                    hi_r = ridx[-1] + 1 if hi_r is None else max(hi_r, ridx[-1] + 1)
        return (lo_r, hi_r) if lo_r is not None else (None, None)

    def hyp_range_for_src(lo: int, hi: int) -> tuple[int, int]:
        lo_r = hi_r = None
        for sidx, hidx in src_hyp_blocks:
            if sidx and sidx[0] >= lo and sidx[-1] < hi:
                if hidx:
                    lo_r = hidx[0] if lo_r is None else min(lo_r, hidx[0])
                    hi_r = hidx[-1] + 1 if hi_r is None else max(hi_r, hidx[-1] + 1)
        return (lo_r, hi_r) if lo_r is not None else (None, None)

    out = []
    prev = 0
    for cut in cut_points:
        lo, hi = prev, cut
        prev = cut
        if lo >= hi:
            continue
        r_lo, r_hi = ref_range_for_src(lo, hi)
        h_lo, h_hi = hyp_range_for_src(lo, hi)
        if r_lo is None or h_lo is None:
            continue  # 无对应内容（0:1/1:0 缺口），跳过，不生成孤立块
        out.append({
            "source_text": " ".join(src_s[lo:hi]),
            "ref_text": " ".join(ref_s[r_lo:r_hi]),
            "hypothesis": " ".join(hyp_s[h_lo:h_hi]),
            "src_sent_count": hi - lo,
            "ref_sent_count": r_hi - r_lo,
            "hyp_sent_count": h_hi - h_lo,
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--semicolon-boundary", action="store_true")
    ap.add_argument("--hyp-field", default="hypothesis")
    ap.add_argument("--src-field", default="source_text")
    ap.add_argument("--ref-field", default="ref_text")
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.input).read_text(encoding="utf-8").splitlines() if l.strip()]
    out_rows = []
    strict_1to1 = 0
    mn_blocks = 0
    for r in rows:
        blocks = align_three_way(r[args.src_field], r[args.ref_field], r[args.hyp_field], semicolon=args.semicolon_boundary)
        for bi, b in enumerate(blocks):
            out_rows.append({
                "sample_id": f"{r['sample_id']}#mn{bi:02d}",
                "parent_id": r["sample_id"],
                "document_id": r.get("document_id", ""),
                **b,
            })
            mn_blocks += 1
            if b.get("src_sent_count") == 1 and b.get("ref_sent_count") == 1 and b.get("hyp_sent_count") == 1:
                strict_1to1 += 1

    with open(args.output, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({
        "input_rows": len(rows),
        "mn_blocks_total": mn_blocks,
        "of_which_1to1to1": strict_1to1,
        "output": args.output,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
