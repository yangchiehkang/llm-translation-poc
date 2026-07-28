#!/usr/bin/env python3
"""T5 补丁 — 逐文档写法分布，替换合并计数。

为什么必须做
------------
V2 暴露：`approval mark` 的"参考实际写法 认证标识(4)"是**跨文档合并**的结果。
逐文档看：R100 用「认证标识」×3、R17 用「认证标识」×1 **且「认证标志」×1**。
合并计数掩盖了 R17 里旧译法也合法，据此改 target 导致净倒扣 −5。

**这个盲区污染全部 17 条相悖术语**（包括 REESS 的 118 个推错实例——也是合并数）。
拉丁缩写探针必须等本表出来之后再跑。

方法与 T5 完全一致，只是把统计拆到 document_id 一级：
对每条相悖术语，逐文档统计参考里 target_term 与候选写法各出现在多少条实例上。
只用参考语料，不看模型输出、不看分数。
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.common.termbase import (  # noqa: E402
    load_termbase, match_terms, hard_required_terms,
)

CORPUS = "outputs/eval/en_zh_689_20260727/full_results.jsonl"
LEDGER = "outputs/analysis/t5_termbase_vs_ref_20260728/t5_ledger.jsonl"
OUT = Path("outputs/analysis/t5_termbase_vs_ref_20260728")


def main() -> None:
    rows = [json.loads(x) for x in Path(CORPUS).read_text(encoding="utf-8").splitlines() if x.strip()]
    led = [json.loads(x) for x in Path(LEDGER).read_text(encoding="utf-8").splitlines() if x.strip()]
    terms = load_termbase("termbase/auto_regulation_terms_v1.csv", "en", "zh")

    inst: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        for t in hard_required_terms(match_terms(r["source_text"], terms)):
            inst[t["source_term"]].append(r)

    focus = [e for e in led if e["class"] in ("相悖", "空格差异")]
    docs = sorted({r["document_id"] for r in rows})
    report = []

    print("=" * 100)
    print("T5 逐文档写法分布（替换合并计数）")
    print("=" * 100)
    print(f"文档：{docs}\n")

    for e in sorted(focus, key=lambda x: -x["instances"]):
        st = e["source_term"]
        tgt = e["target_term"]
        # 候选写法：现译法 + 台账给出的参考写法（可能是 "A / B" 形式）
        cands = [tgt]
        for part in re.split(r"[/、]", e["ref_dominant"] or ""):
            part = re.sub(r"（.*?）", "", part).strip()
            if part and part not in cands:
                cands.append(part)
        per: dict[str, dict[str, int]] = {}
        for d in docs:
            sub = [r for r in inst[st] if r["document_id"] == d]
            if not sub:
                continue
            per[d] = {"实例": len(sub)}
            for c in cands:
                per[d][c] = sum(1 for r in sub if c and c in r["ref_text"])
        # 判定：现译法在某文档里是否其实是主流
        split_risk = []
        for d, v in per.items():
            cur = v.get(tgt, 0)
            best = max((v.get(c, 0) for c in cands[1:]), default=0)
            if cur > 0 and cur >= best:
                split_risk.append(d)

        report.append({"source_term": st, "target_term": tgt,
                       "ref_dominant_merged": e["ref_dominant"],
                       "instances": e["instances"], "per_document": per,
                       "docs_where_current_target_is_fine": split_risk,
                       "one_size_fits_all_safe": not split_risk})

        flag = "  ⚠️ 不可一刀切" if split_risk else ""
        print(f"\n{st}  现译法「{tgt}」  合并计数报的是「{e['ref_dominant']}」{flag}")
        for d, v in per.items():
            parts = "  ".join(f"{c}={v.get(c,0)}" for c in cands)
            print(f"    {d:18s} 实例 {v['实例']:3d}   {parts}")
        if split_risk:
            print(f"    -> 在 {', '.join(split_risk)} 里，现译法「{tgt}」并不劣于候选，"
                  f"改 target 会在这些文档上造成倒扣")

    bad = [r for r in report if not r["one_size_fits_all_safe"]]
    print()
    print("=" * 100)
    print(f"结论：{len(focus)} 条里 **{len(bad)} 条不可一刀切**")
    print("=" * 100)
    for r in bad:
        print(f"  {r['source_term']:34s} 现「{r['target_term']}」 "
              f"在 {','.join(r['docs_where_current_target_is_fine'])} 上不劣")
    (OUT / "t5_per_document.json").write_text(
        json.dumps({"documents": docs, "terms": report,
                    "not_one_size_fits_all": [r["source_term"] for r in bad]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {OUT/'t5_per_document.json'}")


if __name__ == "__main__":
    main()
