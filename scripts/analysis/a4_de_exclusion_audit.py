#!/usr/bin/env python3
"""E — DE 剔除率审计：110 条 exact 最终只剩 40 条，逐条查是谁剔的、剔得对不对。

对照组是 en（9% 剔除率）、ru（26%）、fr（39%）、th（41%）。DE 64% 明显偏高，
且**主要发生在 prefilter 层而不是 acceptance 层**（44% vs 20%）。

本脚本把每一条被剔的样本按规则归类、落盘全文，供人工核对；并对可自动判定的
误伤模式给出计数（不自动改规则，只报数）。

用法：
    python scripts/analysis/a4_de_exclusion_audit.py --lang de
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.evaluation.prepare_da_pairs import (  # noqa: E402
    da_prefilter_reason,
    has_complete_source_end,
)
from scripts.evaluation.acceptance_subset import rules_for  # noqa: E402

V2_DROP = {"R2", "R2a", "R2b", "R3", "R5", "G1", "G2"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aligned", required=True, help="{lang}_zh_aligned_da_samples.jsonl")
    ap.add_argument("--lang", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    rows = [json.loads(l) for l in Path(a.aligned).read_text(encoding="utf-8").splitlines() if l.strip()]
    exact = [r for r in rows if r.get("alignment_method") == "exact_section_scoped"]

    buckets: dict[str, list[dict]] = defaultdict(list)
    survivors = []
    for r in exact:
        r.setdefault("source_char_count", len(r["source_text"]))
        r.setdefault("ref_char_count", len(r["ref_text"]))
        why = da_prefilter_reason(r)
        if why:
            buckets[f"prefilter:{why}"].append(r)
            continue
        hs = rules_for(r, None)
        hit = {x for x, _ in hs} & V2_DROP
        if hit:
            buckets[f"acceptance:{','.join(sorted(hit))}"].append(r)
            continue
        survivors.append(r)

    # 自动可判的疑似误伤模式
    flags: Counter[str] = Counter()
    for key, rs in buckets.items():
        for r in rs:
            src, ref = r["source_text"], r["ref_text"]
            if key.endswith("possible_truncation"):
                # 源文以条款号+完整句收尾却被判截断；或以右括号/引号收尾
                if re.search(r"[.!?;:)\]»”\"']\s*$", src):
                    flags[f"{key} | 源文其实有句末标点"] += 1
                elif has_complete_source_end(src):
                    flags[f"{key} | has_complete_source_end 通过但仍被剔"] += 1
                else:
                    flags[f"{key} | 确实无句末收尾"] += 1
            if key.endswith("length_ratio_abnormal"):
                ratio = len(ref) / max(1, len(src))
                band = ("<0.15" if ratio < 0.15 else "0.15-0.20" if ratio < 0.20
                        else "0.20-0.35" if ratio < 0.35 else ">=0.35")
                flags[f"{key} | ref/src={band}"] += 1
            if key.startswith("acceptance:") and "G1" in key:
                flags[f"{key} | 源文字符数={'短(<200)' if len(src) < 200 else '长(>=200)'}"] += 1

    out = {
        "lang": a.lang,
        "exact_total": len(exact),
        "survivors": len(survivors),
        "drop_rate": round(1 - len(survivors) / max(1, len(exact)), 4),
        "by_bucket": {k: len(v) for k, v in sorted(buckets.items(), key=lambda kv: -len(kv[1]))},
        "auto_flags": dict(flags.most_common()),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))

    dest = Path(a.out)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{a.lang}_exclusion_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(dest / f"{a.lang}_excluded_full.jsonl", "w", encoding="utf-8") as f:
        for key, rs in buckets.items():
            for r in rs:
                f.write(json.dumps({
                    "bucket": key, "sample_id": r["sample_id"],
                    "document_id": r.get("document_id"), "section_no": r.get("section_no"),
                    "scope": r.get("scope", ""),
                    "src_chars": len(r["source_text"]), "ref_chars": len(r["ref_text"]),
                    "ref_over_src": round(len(r["ref_text"]) / max(1, len(r["source_text"])), 3),
                    "source_text": r["source_text"], "ref_text": r["ref_text"],
                }, ensure_ascii=False) + "\n")
    print(f"\nwrote {dest}/{a.lang}_excluded_full.jsonl")


if __name__ == "__main__":
    main()
