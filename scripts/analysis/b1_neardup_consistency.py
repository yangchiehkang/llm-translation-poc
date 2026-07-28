#!/usr/bin/env python3
"""B1 — 近重复条款的译文一致性（纯统计，复用 A1 的相似度口径）。

A1 发现 R100 在 6.2/6.3/6.6/6.8/6.9/6.10 复读同一段验收判据。同样的源文，模型译得
一致吗？组内 DA 极差大 = 模型对同一段文本给出了不同质量的译文 = 纯随机性损失，
可以靠一致性约束回收。极差普遍很小则这条线否掉。

分组：源文相似度 > 0.95 的连通分量（并查集）。相似度口径与 A1 完全一致：
去条款号 -> 小写词 token -> difflib 序列比。
"""
from __future__ import annotations

import json
import re
import statistics as st
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.common.termbase import (  # noqa: E402
    load_termbase, match_terms, hard_required_terms, target_present,
)

SEC = re.compile(r"^\s*(?:\d{1,3}(?:\.\d{1,3})*\.?|[A-Z]\.)\s*")
WORD = re.compile(r"[a-z0-9]+")
THRESH = 0.95
RESULTS = "outputs/eval/en_zh_689_20260727/full_results.jsonl"
OUT = Path("outputs/analysis/b1_neardup_20260728")


def main() -> None:
    rows = [json.loads(x) for x in Path(RESULTS).read_text(encoding="utf-8").splitlines() if x.strip()]
    n = len(rows)
    tk = [WORD.findall(SEC.sub("", r["source_text"]).lower()) for r in rows]

    X = TfidfVectorizer(analyzer="word", ngram_range=(1, 2),
                        token_pattern=r"[a-z0-9]+").fit_transform(" ".join(t) for t in tk)
    C = (X @ X.T).toarray()
    np.fill_diagonal(C, -1.0)

    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    pairs = 0
    for i in range(n):
        for j in np.argsort(-C[i])[:60]:
            j = int(j)
            if j <= i or C[i][j] < 0.30:      # 余弦 0.30 以下不可能到 fuzzy 0.95
                continue
            if SequenceMatcher(None, tk[i], tk[j], autojunk=False).ratio() > THRESH:
                union(i, j)
                pairs += 1

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    groups = {k: v for k, v in groups.items() if len(v) > 1}

    terms = load_termbase("termbase/auto_regulation_terms_v1.csv", "en", "zh")

    def hard_terms(src):
        return hard_required_terms(match_terms(src, terms))

    report = {"threshold": THRESH, "n_rows": n, "n_pairs": pairs,
              "n_groups": len(groups),
              "n_rows_in_groups": sum(len(v) for v in groups.values()), "groups": []}

    print(f"语料 {n} 条；相似度 > {THRESH} 的配对 {pairs} 组连通后得 {len(groups)} 个组，"
          f"覆盖 {sum(len(v) for v in groups.values())} 条\n")

    for gid, idx in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        das = [rows[i]["score_qwen36_40004"] for i in idx]
        rng = max(das) - min(das)
        # 术语一致性：只看**组内每一条源文都要求**的硬术语。
        # 用并集是错的：组内源文只有 >0.95 相似、不是相同，某条源文没有的术语
        # 在它的译文里当然不出现，那不是"不一致"，是源文本来就没有。
        per = [{t["source_term"]: t for t in hard_terms(rows[i]["source_text"])} for i in idx]
        common = set.intersection(*[set(p) for p in per]) if per else set()
        tset = {k: per[0][k] for k in common}
        tcons = {}
        for st_, t in tset.items():
            hits = [target_present(rows[i]["hypothesis_qwen36_40004"], t) for i in idx]
            if len(set(hits)) > 1:
                tcons[st_] = {"target": t.get("target_term"),
                              "present": sum(hits), "of": len(idx)}
        # 译文是否逐字相同
        hyps = {rows[i]["hypothesis_qwen36_40004"] for i in idx}
        # 去掉条款号后源文是否**逐字**相同——temp=0 下这才是纯模型随机性的干净度量。
        # 注意仍不是同一个 prompt：条款号本身还在源文里，模型看得见。
        body = {SEC.sub("", rows[i]["source_text"]).strip() for i in idx}
        hyp_body = {SEC.sub("", rows[i]["hypothesis_qwen36_40004"]).strip() for i in idx}
        g = {"group_id": int(gid), "n": len(idx),
             "sample_ids": [rows[i]["sample_id"] for i in idx],
             "docs": sorted({rows[i]["document_id"] for i in idx}),
             "da": [round(d, 4) for d in das],
             "da_mean": st.mean(das), "da_range": rng,
             "da_std": st.pstdev(das) if len(das) > 1 else 0.0,
             "n_distinct_hypotheses": len(hyps),
             "n_distinct_source_bodies": len(body),
             "identical_source": len(body) == 1,
             "identical_raw_source": len({rows[i]["source_text"] for i in idx}) == 1,
             "n_distinct_hypothesis_bodies": len(hyp_body),
             "n_distinct_refs": len({rows[i]["ref_text"] for i in idx}),
             "n_common_hard_terms": len(tset),
             "inconsistent_terms": tcons}
        report["groups"].append(g)

    rngs = [g["da_range"] for g in report["groups"]]
    stds = [g["da_std"] for g in report["groups"]]
    print("=" * 74)
    print("① 组内 DA 极差分布（组数 = %d）" % len(rngs))
    print("=" * 74)
    print(f"   极差 p50={np.percentile(rngs,50):.4f}  p75={np.percentile(rngs,75):.4f}  "
          f"p90={np.percentile(rngs,90):.4f}  max={max(rngs):.4f}  均值={st.mean(rngs):.4f}")
    print(f"   标准差 p50={np.percentile(stds,50):.4f}  max={max(stds):.4f}")
    for t in (0.02, 0.05, 0.10, 0.20):
        c = sum(1 for r in rngs if r > t)
        print(f"   极差 > {t:.2f} 的组：{c:3d} / {len(rngs)}  ({c/len(rngs):6.1%})")
    report["range_dist"] = {"p50": float(np.percentile(rngs, 50)),
                            "p75": float(np.percentile(rngs, 75)),
                            "p90": float(np.percentile(rngs, 90)),
                            "max": max(rngs), "mean": st.mean(rngs),
                            "over": {str(t): sum(1 for r in rngs if r > t)
                                     for t in (0.02, 0.05, 0.10, 0.20)}}

    print()
    print("=" * 74)
    print("② 可回收的上限：每组都取组内最高分，主数会涨多少")
    print("=" * 74)
    in_grp = {i for v in groups.values() for i in v}
    for tag, flag in (("v2 主数 627", "in_headline_v2_627"), ("v1 主数 650", "in_headline_v1_650")):
        keep = [i for i in range(n) if rows[i][flag]]
        base = st.mean(rows[i]["score_qwen36_40004"] for i in keep)
        lift = {}
        for gidx in groups.values():
            k = [i for i in gidx if rows[i][flag]]
            if k:
                lift[max(k, key=lambda i: rows[i]["score_qwen36_40004"])] = None
                best = max(rows[i]["score_qwen36_40004"] for i in k)
                for i in k:
                    lift[i] = best
        ceil = st.mean(lift.get(i, rows[i]["score_qwen36_40004"]) for i in keep)
        cov = sum(1 for i in keep if i in in_grp)
        print(f"   {tag}: {base:.4f} -> {ceil:.4f}  (+{ceil-base:.4f})，"
              f"组内条数 {cov}/{len(keep)}")
        report[f"ceiling_{flag}"] = {"base": base, "ceiling": ceil, "lift": ceil - base,
                                     "rows_in_groups": cov, "n": len(keep)}

    print()
    print("=" * 74)
    print("③ 混杂因素：组内 DA 极差里有多少不是模型随机性")
    print("=" * 74)
    ident = [g for g in report["groups"] if g["identical_source"]]
    diff = [g for g in report["groups"] if not g["identical_source"]]
    print(f"   去条款号后源文逐字相同的组：{len(ident)} / {len(report['groups'])}"
          f"（含条款号也完全相同的：{sum(1 for g in report['groups'] if g['identical_raw_source'])}）")
    if ident:
        print(f"      这些组的极差 p50={np.percentile([g['da_range'] for g in ident],50):.4f}"
              f"  max={max(g['da_range'] for g in ident):.4f}")
        print(f"      其中**去条款号后译文也逐字相同**的："
              f"{sum(1 for g in ident if g['n_distinct_hypothesis_bodies']==1)} / {len(ident)}"
              f"  <- temp=0 的确定性")
    print(f"   源文不同的组：{len(diff)}，极差 p50="
          f"{np.percentile([g['da_range'] for g in diff],50):.4f}"
          f"  max={max(g['da_range'] for g in diff):.4f}")
    print(f"   参考也不同的组：{sum(1 for g in report['groups'] if g['n_distinct_refs']>1)}"
          f" / {len(report['groups'])}")
    print("   -> 源文与参考都在变，所测极差是模型不一致性的**上界**，不是它本身。")
    report["confounders"] = {
        "identical_source_groups": len(ident),
        "identical_source_and_hyp_body": sum(1 for g in ident
                                             if g["n_distinct_hypothesis_bodies"] == 1),
        "differing_ref_groups": sum(1 for g in report["groups"] if g["n_distinct_refs"] > 1),
    }

    print()
    print("=" * 74)
    print("④ 硬术语的组内一致性（只看组内每条源文都要求的术语）")
    print("=" * 74)
    bad = [g for g in report["groups"] if g["inconsistent_terms"]]
    print(f"   有硬术语译法组内不一致的组：{len(bad)} / {len(report['groups'])}")
    tally = Counter(t for g in bad for t in g["inconsistent_terms"])
    for t, c in tally.most_common(12):
        print(f"      {t}: 在 {c} 个组里不一致")
    print(f"   译文逐字完全相同的组：{sum(1 for g in report['groups'] if g['n_distinct_hypotheses']==1)}"
          f" / {len(report['groups'])}")
    report["inconsistent_term_tally"] = dict(tally)

    print()
    print("=" * 74)
    print("⑤ 极差最大的 3 组：最高分 vs 最低分译文并排")
    print("=" * 74)
    for g in sorted(report["groups"], key=lambda x: -x["da_range"])[:3]:
        idx = [i for i in range(n) if rows[i]["sample_id"] in g["sample_ids"]]
        hi = max(idx, key=lambda i: rows[i]["score_qwen36_40004"])
        lo = min(idx, key=lambda i: rows[i]["score_qwen36_40004"])
        print(f"\n{'='*74}\n组 {g['group_id']}：{g['n']} 条，DA {min(g['da']):.3f}–{max(g['da']):.3f}，"
              f"极差 {g['da_range']:.4f}，"
              f"共同硬术语 {g['n_common_hard_terms']} 个，不一致 {list(g['inconsistent_terms'])}，"
              f"源文相同={g['identical_source']}，参考版本数={g['n_distinct_refs']}")
        for tag, i in (("最高", hi), ("最低", lo)):
            r = rows[i]
            print(f"\n  [{tag} DA={r['score_qwen36_40004']:.4f}] {r['sample_id']}")
            print(f"    源文: {r['source_text'][:230]}")
            print(f"    译文: {r['hypothesis_qwen36_40004'][:230]}")
            print(f"    参考: {r['ref_text'][:230]}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "b1_neardup_stats.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n\n-> {OUT/'b1_neardup_stats.json'}")


if __name__ == "__main__":
    main()
