#!/usr/bin/env python3
"""W1：R3 水印判据的碎片审计 + 误报审计 + 断行鲁棒性回归。

三件事，都在已打分的 689 条上做，不重抽/不重译/不重打分：

  ① 碎片审计：把水印的每一个"部件"单独拿出来当判据，逐个报在 689 条上的命中数，
     以及相对现行 R3 的**新增**条数。如果某个部件的命中集大于现行 R3，说明现行
     "只匹配完整字串"确实漏了断行碎片。
  ② 误报审计：把危险模式（孤立 I. / I / .I.）一并跑，逐条打印命中的正文，
     核对是不是合法内容。
  ③ 断行鲁棒性回归：构造被断行切碎的水印片段，确认加固后的判据能命中，
     且加固前的判据会漏——证明修的是真 bug，不是空转。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.evaluation.acceptance_subset import _watermark_hit  # noqa: E402

CORPUS = "outputs/eval/en_zh_689_20260727/full_results.jsonl"
LEDGER = "outputs/eval/en_zh_689_20260727/acceptance_subset_exclusions.jsonl"

# 现行（修复前）判据：只匹配完整字串
_WM_OLD = ["Applus IDIADA", "I.R.I.S. application", "Download from the",
           "shall not be held responsible", "ECE/TRANS/WP.29"]

# 逐个部件单独当判据跑，看谁比现行多命中
COMPONENTS = {
    "Applus":                 r"Applus",
    "IDIADA":                 r"IDIADA",
    "I.R.I.S.（松散点分）":     r"I\s*\.\s*R\s*\.\s*I\s*\.\s*S",
    "IRIS（裸词）":            r"\bIRIS\b",
    "Download from":          r"Download\s+from\b",
    "powered by":             r"powered\s+by\b",
    "reference purposes only": r"reference\s+purposes\s+only",
    "ECE/TRANS/WP.29":        r"ECE/TRANS/WP\.29",
    "ZH 由Applus":            r"由\s*Applus",
    "ZH IDIADA支持":          r"IDIADA\s*支持",
    "ZH 应用程序下载":         r"应用程序\s*下载",
    "ZH 仅供参考":            r"仅供参考",
}
# 用户点名的高危模式：必须单独审，不能进判据
DANGEROUS = {
    "孤立 I.":  r"(?<![A-Za-z.])I\.(?![A-Za-z0-9])",
    "孤立 I":   r"(?<![A-Za-z.])I(?![A-Za-z0-9.])",
    "\\.I\\.": r"\.I\.",
}


def main() -> None:
    rows = [json.loads(x) for x in Path(CORPUS).read_text(encoding="utf-8").splitlines() if x.strip()]
    cur = {json.loads(x)["sample_id"] for x in Path(LEDGER).read_text(encoding="utf-8").splitlines()
           if x.strip() and "R3" in json.loads(x)["rules"]}
    n = len(rows)
    print(f"语料 {n} 条；现行 R3 命中 {len(cur)} 条\n")

    def hits(pat: str) -> set[str]:
        rx = re.compile(pat)
        return {r["sample_id"] for r in rows
                if rx.search(r["source_text"]) or rx.search(r["ref_text"])}

    report: dict = {"corpus": CORPUS, "n": n, "current_r3_n": len(cur)}

    print("=" * 74)
    print("① 碎片审计：每个水印部件单独当判据，相对现行 R3 的新增")
    print("=" * 74)
    print(f"{'部件':26s} {'命中':>5s} {'新增':>5s}")
    comp = {}
    for name, pat in COMPONENTS.items():
        h = hits(pat)
        comp[name] = {"hits": len(h), "new": sorted(h - cur)}
        print(f"{name:26s} {len(h):5d} {len(h - cur):5d}")
    report["components"] = comp
    total_new = sorted(set().union(*[set(v["new"]) for v in comp.values()]) if comp else set())
    print(f"\n所有部件并集相对现行 R3 的新增：{len(total_new)} 条 {total_new}")
    report["union_new"] = total_new

    print()
    print("=" * 74)
    print("② 误报审计：高危模式逐条核对（这些模式**不**进判据）")
    print("=" * 74)
    danger = {}
    for name, pat in DANGEROUS.items():
        rx = re.compile(pat)
        hs = [r for r in rows if rx.search(r["source_text"]) or rx.search(r["ref_text"])]
        new = [r for r in hs if r["sample_id"] not in cur]
        danger[name] = {"hits": len(hs), "new": len(new), "evidence": []}
        print(f"\n{name}: 命中 {len(hs)}，其中新增 {len(new)}")
        for r in new:
            t = r["source_text"] if rx.search(r["source_text"]) else r["ref_text"]
            m = rx.search(t)
            ctx = t[max(0, m.start() - 55):m.end() + 55]
            print(f"   新增 {r['sample_id']} DA={r['score_qwen36_40004']:.3f}  …{ctx}…")
            danger[name]["evidence"].append(
                {"sample_id": r["sample_id"], "da": r["score_qwen36_40004"], "context": ctx})
    report["dangerous"] = danger

    print()
    print("=" * 74)
    print("③ 断行鲁棒性回归：加固前会漏、加固后能中的碎片")
    print("=" * 74)
    frags = [
        ("Applus 与 IDIADA 被断行分到两段（只剩前半）", "…of its cells; Download from the I.R.I.S. application powered by Applus"),
        ("只剩后半段", "IDIADA. For reference purposes only. 7 (c) The number of cells,"),
        ("I.R.I.S. 被断行插入空格", "Download from the I. R. I. S. application powered by"),
        ("ZH 侧水印被断行（只剩前半）", "可从由Applus"),
        ("ZH 侧水印被断行（只剩后半）", "IDIADA支持的应用程序下载。仅供参考。"),
        ("只剩样板短语，无品牌名（弱标记 >=2）", "Download from the application. For reference purposes only."),
    ]
    neg = [
        ("合法正文：Part I", "1.1. Part I: Safety requirements with respect to the electric power train"),
        ("合法正文：Annex 9I", "The test shall be conducted in accordance with Annex 9I to this Regulation."),
        ("合法正文：powered by 单独出现", "a vehicle powered by an electric motor shall comply with paragraph 5.1."),
        ("合法正文：中文测量描述", "以 250±50 N/min 的速率施加 50±1 N 的垂直向下载荷"),
    ]

    def old_hit(t: str) -> bool:
        return any(w.lower() in t.lower() for w in _WM_OLD)

    ok = True
    print(f"{'':4s}{'场景':44s} {'加固前':>7s} {'加固后':>7s}")
    regression = []
    for label, txt in frags:
        o, nw = old_hit(txt), bool(_watermark_hit(txt))
        ok &= nw
        print(f"    {label:44s} {'中' if o else '漏':>6s} {'中' if nw else '漏':>6s}"
              f"{'   <- 修复点' if nw and not o else ''}")
        regression.append({"case": label, "kind": "positive", "old": o, "new": nw, "pass": nw})
    print()
    for label, txt in neg:
        o, nw = old_hit(txt), bool(_watermark_hit(txt))
        ok &= not nw
        print(f"    {label:44s} {'中' if o else '漏':>6s} {'中' if nw else '漏':>6s}"
              f"{'   <- 误报!' if nw else '   (应为漏)'}")
        regression.append({"case": label, "kind": "negative", "old": o, "new": nw, "pass": not nw})
    report["regression"] = regression
    report["regression_pass"] = bool(ok)
    print(f"\n回归结论：{'全部通过' if ok else '有用例不通过'}")

    print()
    print("=" * 74)
    print("④ 主数与四档敏感性（R3 命中集未变 -> 与封版数逐位相同）")
    print("=" * 74)
    import statistics as st
    r3_rows = [r for r in rows if "R3" in r["exclusion_rules"]]
    r3_in = [r for r in r3_rows if r["in_headline_subset"]]
    das = sorted(r["score_qwen36_40004"] for r in r3_in)
    print(f"R3 命中 {len(r3_rows)} 条，其中 **留在主数里的 {len(r3_in)} 条**，"
          f"均值 {st.mean(das):.4f}")
    print("   这 20 条的 DA：" + " ".join(f"{d:.3f}" for d in das))
    print(f"   落在 [0.36, 0.47] 区间的：{sum(1 for d in das if 0.36 <= d <= 0.47)} 条")
    report["r3_in_headline"] = {"n": len(r3_in), "mean": st.mean(das), "da": das}

    def has(r, *rr):
        return any(x in r["exclusion_rules"] for x in rr)

    tiers = [
        ("严格全集（不剔）", lambda r: False),
        ("最保守：仅剔 R2", lambda r: has(r, "R2")),
        ("中档：R2+R2a+R2b", lambda r: has(r, "R2", "R2a", "R2b")),
        ("中档+G（现行主数）", lambda r: has(r, "R2", "R2a", "R2b", "G1", "G2")),
        ("[假设] 中档+G+R3", lambda r: has(r, "R2", "R2a", "R2b", "G1", "G2", "R3")),
        ("完整子集", lambda r: not r["in_full_subset"]),
    ]
    print(f"\n{'口径':26s} {'n':>5s} {'均值':>9s} {'剔除率':>8s}")
    tbl = []
    for name, pred in tiers:
        k = [r for r in rows if not pred(r)]
        m = st.mean(r["score_qwen36_40004"] for r in k)
        print(f"{name:26s} {len(k):5d} {m:9.4f} {1 - len(k)/n:8.2%}")
        tbl.append({"tier": name, "n": len(k), "mean": m, "exclusion_rate": 1 - len(k)/n})
    report["sensitivity"] = tbl

    out = Path("outputs/analysis/w1_r3_watermark_20260728/r3_fragment_audit.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
