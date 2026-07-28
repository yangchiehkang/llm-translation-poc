#!/usr/bin/env python3
"""A1 门槛数：模糊匹配检索的可行性统计。纯统计，不建索引、不调模型。

对 689 条每一条，在其余 688 条里检索源文最相似的一条，报相似度分布、
阈值命中数、长度带拆分、近重复 vs 真模糊匹配、跨文档匹配率。

相似度口径：去掉条款号后，小写词 token 上的 difflib 序列比（等价 CAT 工具的
fuzzy match score）。TF-IDF 余弦只用作 top-60 预筛，不作为报数口径。
"""
import json, re, statistics as st
from difflib import SequenceMatcher
from collections import Counter
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

SEC = re.compile(r"^\s*(?:\d{1,3}(?:\.\d{1,3})*\.?|[A-Z]\.)\s*")
WORD = re.compile(r"[a-z0-9]+")
ROWS = [json.loads(l) for l in
        open("outputs/eval/en_zh_689_20260727/full_results.jsonl")]

def toks(s):
    return WORD.findall(SEC.sub("", s).lower())

TK = [toks(r["source_text"]) for r in ROWS]
DOC = [r["document_id"] for r in ROWS]
N = len(ROWS)

def band(n):
    return "<100" if n < 100 else "100-199" if n < 200 else "200-299" if n < 300 else "300+"
BAND = [band(r["source_char_count"]) for r in ROWS]
BANDS = ["<100", "100-199", "200-299", "300+"]

# --- top-60 预筛（TF-IDF 词 1-2gram 余弦），再在候选上算真 fuzzy score ---
V = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), token_pattern=r"[a-z0-9]+",
                    lowercase=True)
X = V.fit_transform(" ".join(t) for t in TK)
COS = (X @ X.T).toarray()
np.fill_diagonal(COS, -1.0)

def fuzzy(i, j):
    return SequenceMatcher(None, TK[i], TK[j], autojunk=False).ratio()

def best(i, allowed):
    """在 allowed（下标集合）里找 i 的最佳 fuzzy 匹配，返回 (score, j)。"""
    cand = [j for j in np.argsort(-COS[i])[:60] if j in allowed]
    for j in allowed:                      # 余弦为 0 的兜底：保证 allowed 非空时有解
        if len(cand) == 0:
            cand = [j]
            break
    if not cand:
        return (0.0, -1)
    scored = [(fuzzy(i, j), j) for j in cand]
    return max(scored)

ALL = set(range(N))
BY_DOC = {d: {i for i in range(N) if DOC[i] == d} for d in set(DOC)}

res = []
for i in range(N):
    s_all, j_all = best(i, ALL - {i})
    other = ALL - BY_DOC[DOC[i]]
    s_x, j_x = best(i, other)
    same = BY_DOC[DOC[i]] - {i}
    s_in, j_in = best(i, same)
    res.append(dict(i=i, sid=ROWS[i]["sample_id"], doc=DOC[i], band=BAND[i],
                    chars=ROWS[i]["source_char_count"],
                    hl=ROWS[i]["in_headline_subset"],
                    top1=s_all, top1_j=int(j_all),
                    top1_cross=s_x, top1_cross_j=int(j_x),
                    top1_same=s_in, top1_same_j=int(j_in)))

def q(v, p):
    return float(np.percentile(v, p)) if v else float("nan")

def dist(v, label):
    return (f"{label:22s} n={len(v):4d}  p50={q(v,50):.3f} p75={q(v,75):.3f} "
            f"p90={q(v,90):.3f} max={max(v):.3f}" if v else f"{label:22s} n=0")

def counts(v):
    return {t: sum(1 for x in v if x > t) for t in (0.95, 0.85, 0.75, 0.65, 0.50)}

out = {}
print("=" * 78)
print("① top-1 相似度分布（全语料排除自身）")
print("=" * 78)
allv = [r["top1"] for r in res]
print(dist(allv, "全部 689"))
out["top1_all"] = dict(n=N, p50=q(allv, 50), p75=q(allv, 75), p90=q(allv, 90),
                       max=max(allv), counts=counts(allv))

print()
print("=" * 78)
print("② 阈值命中数（全语料排除自身）")
print("=" * 78)
c = counts(allv)
for t in (0.95, 0.85, 0.75, 0.65, 0.50):
    print(f"   top-1 > {t:.2f} : {c[t]:4d} / {N}  ({c[t]/N:6.2%})")

print()
print("=" * 78)
print("③ 按长度带拆（关键：长段有没有匹配）")
print("=" * 78)
print(f"{'长度带':>10s} {'n':>5s} {'p50':>7s} {'p75':>7s} {'p90':>7s} {'max':>7s} "
      f"{'>.95':>6s} {'>.85':>6s} {'>.75':>6s} {'>.65':>6s}")
out["by_band"] = {}
for b in BANDS:
    v = [r["top1"] for r in res if r["band"] == b]
    c = counts(v)
    print(f"{b:>10s} {len(v):5d} {q(v,50):7.3f} {q(v,75):7.3f} {q(v,90):7.3f} "
          f"{max(v):7.3f} {c[0.95]:6d} {c[0.85]:6d} {c[0.75]:6d} {c[0.65]:6d}")
    out["by_band"][b] = dict(n=len(v), p50=q(v, 50), p75=q(v, 75), p90=q(v, 90),
                             max=max(v), counts=c)

print()
print("=" * 78)
print("④ 近重复 vs 真模糊匹配（全语料排除自身）")
print("=" * 78)
nd = [r for r in res if r["top1"] > 0.95]
fz = [r for r in res if 0.75 < r["top1"] <= 0.95]
no = [r for r in res if r["top1"] <= 0.75]
print(f"   近重复   top-1 > 0.95        : {len(nd):4d} ({len(nd)/N:6.2%})")
print(f"   真模糊   0.75 < top-1 <= 0.95: {len(fz):4d} ({len(fz)/N:6.2%})")
print(f"   无匹配   top-1 <= 0.75       : {len(no):4d} ({len(no)/N:6.2%})")
print("   近重复的长度带分布:", dict(Counter(r["band"] for r in nd)))
print("   真模糊的长度带分布:", dict(Counter(r["band"] for r in fz)))
print("   近重复中跨文档的:", sum(1 for r in nd if DOC[r["top1_j"]] != r["doc"]))
out["near_dup"] = dict(near_dup=len(nd), fuzzy=len(fz), none=len(no),
                       near_dup_bands=dict(Counter(r["band"] for r in nd)),
                       fuzzy_bands=dict(Counter(r["band"] for r in fz)))

print()
print("=" * 78)
print("⑤ 跨文档匹配率（翻 R100 只能从 R17 检索，反之亦然）")
print("=" * 78)
for d in sorted(BY_DOC):
    v = [r["top1_cross"] for r in res if r["doc"] == d]
    c = counts(v)
    print(f"   {d:16s} n={len(v):4d}  p50={q(v,50):.3f} p75={q(v,75):.3f} "
          f"p90={q(v,90):.3f} max={max(v):.3f}")
    print(f"   {'':16s}      >.95={c[0.95]:3d}  >.85={c[0.85]:3d}  >.75={c[0.75]:3d}  "
          f">.65={c[0.65]:3d}  >.50={c[0.50]:3d}")
xall = [r["top1_cross"] for r in res]
print(f"\n   合计 689: p50={q(xall,50):.3f} p90={q(xall,90):.3f} max={max(xall):.3f} "
      f" >.75={counts(xall)[0.75]}  >.65={counts(xall)[0.65]}")
print("\n   跨文档 × 长度带:")
print(f"{'长度带':>10s} {'n':>5s} {'p50':>7s} {'p90':>7s} {'max':>7s} "
      f"{'>.85':>6s} {'>.75':>6s} {'>.65':>6s}")
out["cross_doc_by_band"] = {}
for b in BANDS:
    v = [r["top1_cross"] for r in res if r["band"] == b]
    c = counts(v)
    print(f"{b:>10s} {len(v):5d} {q(v,50):7.3f} {q(v,90):7.3f} {max(v):7.3f} "
          f"{c[0.85]:6d} {c[0.75]:6d} {c[0.65]:6d}")
    out["cross_doc_by_band"][b] = dict(n=len(v), p50=q(v, 50), p90=q(v, 90),
                                       max=max(v), counts=c)

print()
print("=" * 78)
print("⑥ 同文档 vs 跨文档（同一条的两个数并排）")
print("=" * 78)
sv = [r["top1_same"] for r in res]
print(f"   同文档 top-1: p50={q(sv,50):.3f} p90={q(sv,90):.3f}  >.95={counts(sv)[0.95]}  >.75={counts(sv)[0.75]}")
print(f"   跨文档 top-1: p50={q(xall,50):.3f} p90={q(xall,90):.3f}  >.95={counts(xall)[0.95]}  >.75={counts(xall)[0.75]}")
print(f"   top-1 来自同文档的条数: {sum(1 for r in res if DOC[r['top1_j']] == r['doc'])} / {N}")

print()
print("=" * 78)
print("⑦ 主数子集（650）复核 + 300+ 计数")
print("=" * 78)
hl = [r for r in res if r["hl"]]
print(f"   主数 n={len(hl)}；其中 300+ = {sum(1 for r in hl if r['band']=='300+')}")
print(f"   严格全集 300+ = {sum(1 for r in res if r['band']=='300+')}")
hv = [r["top1"] for r in hl]
print(f"   主数 top-1: p50={q(hv,50):.3f} p90={q(hv,90):.3f} >.95={counts(hv)[0.95]} >.75={counts(hv)[0.75]}")

print()
print("=" * 78)
print("⑧ 近重复样例（人工可核验）")
print("=" * 78)
for r in sorted(nd, key=lambda x: -x["top1"])[:5]:
    j = r["top1_j"]
    print(f"\n  {r['sid']}  <->  {ROWS[j]['sample_id']}   fuzzy={r['top1']:.3f}"
          f"  ({'跨文档' if DOC[j]!=r['doc'] else '同文档'})")
    print(f"    A: {ROWS[r['i']]['source_text'][:150]}")
    print(f"    B: {ROWS[j]['source_text'][:150]}")
print()
print("⑨ 300+ 长段里 top-1 最高的 5 条（这条路对缺口有没有用，看这里）")
for r in sorted([x for x in res if x["band"] == "300+"], key=lambda x: -x["top1"])[:5]:
    j = r["top1_j"]
    print(f"\n  {r['sid']} ({r['chars']}字) <-> {ROWS[j]['sample_id']} fuzzy={r['top1']:.3f}"
          f"  ({'跨文档' if DOC[j]!=r['doc'] else '同文档'})  跨文档最佳={r['top1_cross']:.3f}")
    print(f"    A: {ROWS[r['i']]['source_text'][:140]}")
    print(f"    B: {ROWS[j]['source_text'][:140]}")

json.dump({"summary": out,
           "per_row": [{k: v for k, v in r.items() if k != "i"} for r in res]},
          open("outputs/analysis/a1_retrieval_20260728/a1_retrieval_stats.json", "w"), ensure_ascii=False, indent=2)
print("\n\n-> outputs/analysis/a1_retrieval_20260728/a1_retrieval_stats.json")
