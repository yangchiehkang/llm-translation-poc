#!/usr/bin/env python3
# 结果汇总脚本：按 sample_id 或 seg_id 合并 TCR、QE、DA 等指标表。
# 运行位置：本地；用于生成统一分析表和阶段汇总材料。

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.io_utils import read_table, write_jsonl, write_csv, row_key


def parse_metric_spec(spec: str) -> tuple[str, str]:
    if ":" in spec:
        path, prefix = spec.split(":", 1)
        return path, prefix
    return spec, Path(spec).stem


def index_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {}
    for idx, row in enumerate(rows, 1):
        key = row_key(row, idx)
        if key:
            out[key] = row
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge TCR/QE/DA metrics by sample_id or seg_id.")
    ap.add_argument("--base", required=True, help="Base JSONL/CSV table.")
    ap.add_argument("--metric", action="append", default=[], help="Metric file, optionally path:prefix. Can repeat.")
    ap.add_argument("--output", required=True, help="Output .jsonl or .csv.")
    args = ap.parse_args()

    rows = read_table(args.base)
    merged = [dict(row) for row in rows]
    key_to_pos = {row_key(row, idx): i for i, row in enumerate(merged, 1)}

    for spec in args.metric:
        path, prefix = parse_metric_spec(spec)
        metric_rows = read_table(path)
        for idx, metric_row in enumerate(metric_rows, 1):
            key = row_key(metric_row, idx)
            if key not in key_to_pos:
                continue
            target = merged[key_to_pos[key]]
            for k, v in metric_row.items():
                if k in {"sample_id", "seg_id", "id", "segment_id"}:
                    continue
                target[f"{prefix}_{k}"] = v

    if args.output.lower().endswith(".csv"):
        write_csv(args.output, merged)
    else:
        write_jsonl(args.output, merged)
    print(json.dumps({"base": args.base, "metrics": args.metric, "output": args.output, "rows": len(merged)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
