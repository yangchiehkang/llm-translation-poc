#!/usr/bin/env python3
"""验收子集口径的唯一定义处：把剔除台账翻译成子集归属、主数与敏感性表。

在此之前 `in_headline_subset` 是临时算出来写进 full_results 的，口径没有落成代码。
R3 促级是一次**口径变更**，必须先把口径变成可复现的脚本，才谈得上改它。

口径版本（两个主数永远并排出现，不允许只报一个）
------------------------------------------------
v1  中档+G        R2/R2a/R2b/G1/G2                 650 / 0.8434   封版口径，保留
v2  中档+G+R3/R5/β R2/R2a/R2b/G1/G2/R3/R5/β        627 / 0.8564   现行主数

注：627 不是 630。630/0.8559 是"仅促 R3"的数；划线标准同时让 R5（2 条）与 β（1 条）过线，
按标准执行得到 627/0.8564。标准是决策，630 是引用的中间数——以标准为准，两个都列在敏感性表里。

v2 的划线标准：**判据能否直接从原始文档核验、与任何分数无关。**
  过线 R3（源文里躺着 "Download from the I.R.I.S. application powered by Applus IDIADA"，
          翻 PDF 一眼可见）
  过线 R5（参考里的孤立单数字连排，是上下标被抽平的签名，对照 PDF 可见）
  过线 β
  不过线 —— 那 9 条低比值残余：阈值是从全集比值分布统计推出来的，不是从原始文档直接可见的
          事实，证据等级不同，维持不动。
  不过线 —— B（参考过覆盖）与 G 以外的粒度类：B 已在 v1 之外单列，此处不动。

R4（表格行）两个版本都不算"剔除"，它转专项指标（转数字一致率/格式保持率），单独计。

⚠ 披露：R3/R5/β 促级发生在语料封版之后，决策时已知其效应为 **+0.0130**（0.8434 -> 0.8564）。
促级依据是判据可从原始 PDF 直接核验，不是它抬分。见 outputs/eval/.../README.md 的决策记录。
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from collections import Counter
from pathlib import Path

# 主数口径：剔除这些规则命中的行
HEADLINE_V1 = ("R2", "R2a", "R2b", "G1", "G2")
HEADLINE_V2 = ("R2", "R2a", "R2b", "G1", "G2", "R3", "R5", "β")

# 敏感性阶梯：(标签, 剔除的规则集合 或 None 表示"全部规则")
TIERS: list[tuple[str, tuple[str, ...] | None]] = [
    ("严格全集（不剔）", ()),
    ("最保守：仅剔 R2", ("R2",)),
    ("中档：R2+R2a+R2b", ("R2", "R2a", "R2b")),
    ("v1 中档+G（封版口径，保留并报）", HEADLINE_V1),
    ("[参照] 中档+G+R3（仅促 R3）", ("R2", "R2a", "R2b", "G1", "G2", "R3")),
    ("v2 中档+G+R3/R5/β（现行主数）", HEADLINE_V2),
    ("完整子集（全部规则，R4 转专项）", None),
]
SCORE_KEYS = ("score", "score_qwen36_40004")


def score_of(row: dict) -> float:
    for k in SCORE_KEYS:
        if k in row:
            return float(row[k])
    raise KeyError(f"no score field in {row.get('sample_id')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, help="full_results.jsonl（含分数）")
    ap.add_argument("--ledger", required=True, help="acceptance_subset_exclusions.jsonl")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--write-results", action="store_true",
                    help="就地重写 full_results.jsonl 的子集标记字段")
    ap.add_argument("--batch-label", required=True,
                    help="译文批次标签，必填。任何一张 DA 表都必须带它——"
                         "0.8434 与 0.8409 差的不是口径而是译文批次，混过一次就够了。")
    args = ap.parse_args()

    rows = [json.loads(x) for x in Path(args.results).read_text(encoding="utf-8").splitlines() if x.strip()]
    ledger = {}
    for x in Path(args.ledger).read_text(encoding="utf-8").splitlines():
        if x.strip():
            e = json.loads(x)
            ledger[e["sample_id"]] = e
    n = len(rows)

    def hit(sid: str, rules: tuple[str, ...]) -> bool:
        e = ledger.get(sid)
        return bool(e) and any(r in e["rules"] for r in rules)

    def keep(rules: tuple[str, ...] | None) -> list[dict]:
        if rules is None:                       # 完整子集：任何规则命中即剔
            return [r for r in rows if r["sample_id"] not in ledger]
        return [r for r in rows if not hit(r["sample_id"], rules)]

    tiers = []
    for label, rules in TIERS:
        k = keep(rules)
        tiers.append({"label": label, "rules": list(rules) if rules is not None else "ALL",
                      "n": len(k), "mean": st.mean(score_of(r) for r in k),
                      "exclusion_rate": round(1 - len(k) / n, 6)})

    v1 = {r["sample_id"] for r in keep(HEADLINE_V1)}
    v2 = {r["sample_id"] for r in keep(HEADLINE_V2)}
    full = {r["sample_id"] for r in keep(None)}
    promoted = sorted(v1 - v2)
    pv = [score_of(r) for r in rows if r["sample_id"] in promoted]

    for r in rows:
        s = r["sample_id"]
        r["in_headline_subset"] = s in v2          # 现行主数 = v2
        r["in_headline_v2_627"] = s in v2
        r["in_headline_v1_650"] = s in v1
        r["in_full_subset"] = s in full
        r["exclusion_rules"] = sorted(ledger[s]["rules"]) if s in ledger else []

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.write_results:
        Path(args.results).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    sens = {
        "batch_label": args.batch_label,
        "note": "v1 与 v2 两个主数永远并排出现；只报其一即为违规。"
                " 本表所有 DA 均出自 batch_label 标注的同一批译文。",
        "disclosure": ("R3/R5/β 促级发生在语料封版之后。决策时已知其效应为 +0.0130"
                       f"（{tiers[3]['mean']:.4f} -> {tiers[5]['mean']:.4f}）。"
                       "促级依据是判据可从原始 PDF 直接核验，与分数无关。"),
        "headline_v1_650": {"label": TIERS[3][0], "rules": list(HEADLINE_V1),
                            "n": len(v1), "mean": tiers[3]["mean"]},
        "headline_v2_627": {"label": TIERS[5][0], "rules": list(HEADLINE_V2),
                            "n": len(v2), "mean": tiers[5]["mean"]},
        "promoted_out_by_v2": {
            "n": len(promoted), "mean": st.mean(pv), "min": min(pv), "max": max(pv),
            "sample_ids": promoted,
            "rule_hits": dict(Counter(r for s in promoted for r in ledger[s]["rules"])),
        },
        "tiers": tiers,
        "full_n": n,
    }
    (out_dir / "sensitivity.json").write_text(
        json.dumps(sens, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"译文批次：{args.batch_label}")
    print(f"{'口径':36s} {'n':>5s} {'均值':>9s} {'剔除率':>8s}")
    for t in tiers:
        print(f"{t['label']:36s} {t['n']:5d} {t['mean']:9.4f} {t['exclusion_rate']:8.2%}")
    print(f"\nv2 相对 v1 多剔 {len(promoted)} 条，这些行均值 {st.mean(pv):.4f} "
          f"(min {min(pv):.3f} / max {max(pv):.3f})")
    print(f"多剔的规则构成：{sens['promoted_out_by_v2']['rule_hits']}")
    print(f"\n-> {out_dir/'sensitivity.json'}")


if __name__ == "__main__":
    main()
