#!/usr/bin/env python3
"""V2 — 臂 A（T4 术语库）vs 臂 B（T4+13）配对报数。

两臂同一会话、同一脚本、同一端点（40004/temp0）、689 全量重译，
唯一差异是 `--termbase`。因此逐条可比，不受 T4 混合基线不可复现的污染。
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.common.termbase import (  # noqa: E402
    load_termbase, match_terms, hard_required_terms, target_present,
)

D = Path("outputs/eval/en_zh_689_v2_20260728")
TB_A = "termbase/auto_regulation_terms_v1.csv"
TB_B = "/private/tmp/claude-501/-Users-william-Working-llm-translation-poc/" \
       "b90cf1e6-34aa-4651-b87c-466e4d25a8b4/scratchpad/termbase_V2.csv"
LEDGER = "outputs/eval/en_zh_689_20260727/acceptance_subset_exclusions.jsonl"
CHANGED = {"enclosure", "high voltage bus", "electric power train", "electrical chassis",
           "venting", "overcurrent protection", "thermal propagation", "approval mark",
           "overcharge protection", "exposed conductive part", "traction battery",
           "conductive connection", "energy absorption test"}
V2_RULES = {"R2", "R2a", "R2b", "G1", "G2", "R3", "R5", "β"}
V1_RULES = {"R2", "R2a", "R2b", "G1", "G2"}


def band(n):
    return "<100" if n < 100 else "100-199" if n < 200 else "200-299" if n < 300 else "300+"


def main() -> None:
    A = {json.loads(l)["sample_id"]: json.loads(l) for l in (D / "armA_scores.jsonl").open(encoding="utf-8")}
    B = {json.loads(l)["sample_id"]: json.loads(l) for l in (D / "armB_scores.jsonl").open(encoding="utf-8")}
    led = {}
    for l in Path(LEDGER).read_text(encoding="utf-8").splitlines():
        if l.strip():
            e = json.loads(l)
            led[e["sample_id"]] = set(e["rules"])
    ta = load_termbase(TB_A, "en", "zh")
    tb = load_termbase(TB_B, "en", "zh")
    ids = sorted(A)

    # ---- TCR，各自用自己那臂的术语库 ----
    def tcr(scores, terms, tag):
        tt = th = sn = sp = 0
        per = defaultdict(lambda: [0, 0])
        for i in ids:
            r = scores[i]
            req = hard_required_terms(match_terms(r["source_text"], terms))
            if not req:
                continue
            sn += 1
            ok = True
            for t in req:
                tt += 1
                per[t["source_term"]][0] += 1
                if target_present(r["hypothesis_translation"], t):
                    th += 1
                    per[t["source_term"]][1] += 1
                else:
                    ok = False
            sp += ok
        print(f"  {tag}: 术语级 {th}/{tt} = {th/tt:.4%}   样本级 {sp}/{sn} = {sp/sn:.4%}")
        return per, th / tt, sp / sn

    print("=" * 78)
    print("① TCR 门禁（<95% 一律否决）")
    print("=" * 78)
    pa, ta_r, sa_r = tcr(A, ta, "臂A T4术语库  ")
    pb, tb_r, sb_r = tcr(B, tb, "臂B T4+13     ")
    print(f"\n  术语级 {ta_r:.4%} -> {tb_r:.4%}  ({tb_r-ta_r:+.4%})")
    print(f"  样本级 {sa_r:.4%} -> {sb_r:.4%}  ({sb_r-sa_r:+.4%})")
    print(f"  门禁：{'通过' if tb_r >= 0.95 else '**否决**'}（术语级 {tb_r:.2%} vs 95%）")

    print()
    print("=" * 78)
    print("② 逐术语改前/改后命中（本批 13 条）")
    print("=" * 78)
    print(f"{'源术语':30s} {'A译法':12s} {'B译法':12s} {'A命中':>10s} {'B命中':>10s} {'净':>5s}")
    amap = {t["source_term"]: t for t in ta}
    bmap = {t["source_term"]: t for t in tb}
    net_total = 0
    for s in sorted(CHANGED):
        x, y = pa.get(s, [0, 0]), pb.get(s, [0, 0])
        at = amap.get(s, {}).get("target_term", "?")
        bt = bmap.get(s, {}).get("target_term", "?")
        if s == "energy absorption test":
            bt += "(+alias)"
        net = y[1] - x[1]
        net_total += net
        flag = "  <- 净倒扣" if net < 0 else ""
        print(f"{s[:29]:30s} {at[:11]:12s} {bt[:11]:12s} "
              f"{x[1]:4d}/{x[0]:<5d} {y[1]:4d}/{y[0]:<5d} {net:+5d}{flag}")
    print(f"\n  本批 13 条净变化：{net_total:+d} 个命中实例")

    print()
    print("=" * 78)
    print("③ DA 七档（两臂并排）")
    print("=" * 78)
    tiers = [("严格全集", set()), ("最保守 仅剔R2", {"R2"}),
             ("中档 R2+R2a+R2b", {"R2", "R2a", "R2b"}),
             ("v1 中档+G", V1_RULES), ("[参照] 仅促R3", V1_RULES | {"R3"}),
             ("v2 中档+G+R3/R5/β", V2_RULES), ("完整子集", None)]
    print(f"{'口径':24s} {'n':>5s} {'臂A':>8s} {'臂B':>8s} {'增益':>9s}")
    res = {}
    for name, rr in tiers:
        k = [i for i in ids if i not in led] if rr is None else [i for i in ids if not (led.get(i, set()) & rr)]
        a = st.mean(float(A[i]["score"]) for i in k)
        b = st.mean(float(B[i]["score"]) for i in k)
        res[name] = (len(k), a, b, b - a)
        print(f"{name:24s} {len(k):5d} {a:8.4f} {b:8.4f} {b-a:+9.4f}")
    n, a, b, g = res["v2 中档+G+R3/R5/β"]
    print(f"\n  **判据：v2 口径增益 {g:+.4f}，阈值 +0.005 -> "
          f"{'通过' if g >= 0.005 else '**未达标，术语库杠杆关闭**'}**")

    print()
    print("=" * 78)
    print("④ DA 逐条涨跌，按『是否含被改术语』拆两组")
    print("=" * 78)
    hit_ids = []
    for i in ids:
        ms = {m["source_term"] for m in match_terms(A[i]["source_text"], ta)}
        if ms & CHANGED:
            hit_ids.append(i)
    hs = set(hit_ids)
    v2keep = [i for i in ids if not (led.get(i, set()) & V2_RULES)]
    for tag, L in (("全部 689", ids), ("v2 保留 627", v2keep)):
        g1 = [i for i in L if i in hs]
        g0 = [i for i in L if i not in hs]
        print(f"\n  {tag}:")
        for nm, G in (("含被改术语", g1), ("不含", g0)):
            if not G:
                continue
            d = [float(B[i]["score"]) - float(A[i]["score"]) for i in G]
            up = sum(1 for x in d if x > 1e-9)
            dn = sum(1 for x in d if x < -1e-9)
            same = len(d) - up - dn
            print(f"    {nm:10s} n={len(G):4d}  均值Δ={st.mean(d):+.4f}  "
                  f"涨 {up:3d} 跌 {dn:3d} 平 {same:3d}")
        # 净效应归因
        if g1 and g0:
            print(f"    -> 含被改术语组贡献了 v2 口径全部增益的 "
                  f"{st.mean([float(B[i]['score'])-float(A[i]['score']) for i in g1])*len(g1)/max(sum(float(B[i]['score'])-float(A[i]['score']) for i in L),1e-9):.0%}")

    print()
    print("=" * 78)
    print("⑤ 按长度带（v2 保留 627）")
    print("=" * 78)
    src_len = {i: len(A[i]["source_text"]) for i in ids}
    print(f"{'长度带':>10s} {'n':>5s} {'臂A':>8s} {'臂B':>8s} {'增益':>9s} {'含改术语':>8s}")
    for bnd in ("<100", "100-199", "200-299", "300+"):
        L = [i for i in v2keep if band(src_len[i]) == bnd]
        if not L:
            continue
        a = st.mean(float(A[i]["score"]) for i in L)
        b = st.mean(float(B[i]["score"]) for i in L)
        print(f"{bnd:>10s} {len(L):5d} {a:8.4f} {b:8.4f} {b-a:+9.4f} {sum(1 for i in L if i in hs):8d}")

    print()
    print("=" * 78)
    print("⑥ enclosure 专项（两法都排前列的唯一一条）")
    print("=" * 78)
    enc = [i for i in ids if "enclosure" in {m["source_term"] for m in match_terms(A[i]["source_text"], ta)}]
    enck = [i for i in enc if i in set(v2keep)]
    d = [float(B[i]["score"]) - float(A[i]["score"]) for i in enck]
    print(f"  含 enclosure 且在 v2 保留集内：{len(enck)} 条")
    print(f"  均值Δ={st.mean(d):+.4f}  涨 {sum(1 for x in d if x>1e-9)} "
          f"跌 {sum(1 for x in d if x<-1e-9)} 平 {sum(1 for x in d if abs(x)<=1e-9)}")
    print(f"  臂A {st.mean(float(A[i]['score']) for i in enck):.4f} -> "
          f"臂B {st.mean(float(B[i]['score']) for i in enck):.4f}")
    top = sorted(enck, key=lambda i: float(B[i]["score"]) - float(A[i]["score"]))
    print("\n  跌最多 3 条 / 涨最多 3 条：")
    for i in top[:3] + top[-3:]:
        dd = float(B[i]["score"]) - float(A[i]["score"])
        print(f"    {i}  {float(A[i]['score']):.3f} -> {float(B[i]['score']):.3f}  {dd:+.3f}")

    out = Path("outputs/analysis/v2_termbase_20260728")
    out.mkdir(parents=True, exist_ok=True)
    (out / "v2_compare.json").write_text(json.dumps({
        "tcr": {"armA_term": ta_r, "armA_sample": sa_r, "armB_term": tb_r, "armB_sample": sb_r},
        "tiers": {k: {"n": v[0], "armA": v[1], "armB": v[2], "gain": v[3]} for k, v in res.items()},
        "per_term": {s: {"A": pa.get(s, [0, 0]), "B": pb.get(s, [0, 0])} for s in sorted(CHANGED)},
        "n_rows_with_changed_terms": len(hit_ids),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out/'v2_compare.json'}")


if __name__ == "__main__":
    main()
