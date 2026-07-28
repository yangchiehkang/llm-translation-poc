#!/usr/bin/env python3
"""V2 — 从 T5 台账生成 B 臂术语库（T4 + 13 条改动）。不改生产那份。

⚠️ 生产与评测共用 `termbase/auto_regulation_terms_v1.csv`（`.env` 的 TERMBASE_PATH），
改它会立刻改变生产译文。本脚本**只写新文件**，源文件只读。

本批 13 条（T5 相悖 17 条 − 4 条拉丁缩写）：
  12 条改 target_term，1 条（energy absorption test）只加 target_alias。
不进本批：
  REESS / state of charge / IPXXB / Rechargeable Electrical Energy Storage System
      —— 新译法与源文同形的拉丁缩写，属 T3 里模型拒绝执行恒等指令那个坑，单独排探针轮次
  3-D H machine —— 空格规范问题不是译法冲突，改法不同
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

# source_term -> 新 target_term。依据 outputs/analysis/t5_termbase_vs_ref_20260728/t5_ledger.jsonl
RETARGET = {
    "enclosure": "密闭室",
    "high voltage bus": "高压总线",
    "electric power train": "电动力系统",
    "electrical chassis": "电气底盘",
    "venting": "通风",
    "overcurrent protection": "过流保护",
    "thermal propagation": "热传播",
    "approval mark": "认证标识",
    "overcharge protection": "过充保护",
    "exposed conductive part": "外露导电部件",
    "traction battery": "动力蓄电池",
    "conductive connection": "传导连接",
}
# 参考里两种写法并存 -> 加别名，不改 target（改了会把另一种判成失败）
ADD_TARGET_ALIAS = {
    "energy absorption test": ["能量耗散试验", "吸能试验"],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-csv", default="termbase/auto_regulation_terms_v1.csv")
    ap.add_argument("--out-csv", required=True)
    args = ap.parse_args()

    src = Path(args.in_csv)
    with src.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = list(reader.fieldnames or [])
        rows = list(reader)
    if "target_alias" not in cols:
        cols.append("target_alias")

    applied, aliased, missing = [], [], []
    seen = set()
    for r in rows:
        if r.get("source_lang") != "en" or r.get("target_lang") != "zh":
            continue
        st = (r.get("source_term") or "").strip()
        if st in RETARGET:
            seen.add(st)
            old = r.get("target_term")
            r["target_term"] = RETARGET[st]
            applied.append((r["term_id"], st, old, RETARGET[st]))
        if st in ADD_TARGET_ALIAS:
            seen.add(st)
            cur = [a for a in (r.get("target_alias") or "").split("|") if a.strip()]
            for a in ADD_TARGET_ALIAS[st]:
                if a not in cur:
                    cur.append(a)
            r["target_alias"] = "|".join(cur)
            aliased.append((r["term_id"], st, r.get("target_term"), r["target_alias"]))

    for st in list(RETARGET) + list(ADD_TARGET_ALIAS):
        if st not in seen:
            missing.append(st)
    if missing:
        raise SystemExit(f"以下术语在术语库里没找到，拒绝产出半成品：{missing}")

    out = Path(args.out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})

    print(f"源: {src}  ->  出: {out}")
    print(f"\n改 target_term（{len(applied)} 条）:")
    for tid, st, o, n in applied:
        print(f"  {tid}  {st:32s} {o} -> {n}")
    print(f"\n加 target_alias（{len(aliased)} 条，不改 target）:")
    for tid, st, t, a in aliased:
        print(f"  {tid}  {st:32s} target={t}  alias={a}")
    print(f"\n合计 {len(applied)+len(aliased)} 条改动。源文件未被修改。")


if __name__ == "__main__":
    main()
