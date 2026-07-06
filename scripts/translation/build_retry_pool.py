#!/usr/bin/env python3
# 翻译辅助脚本：从 TCR 失败结果中筛选需要 retry_repair 的样本。
# 运行位置：本地；输出重试样本池，供服务器侧 Qwen-Max 定向修复术语问题。

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.io_utils import read_jsonl, write_jsonl, pick_first, row_key
from scripts.common.prompting import classify_sample
from scripts.common.termbase import get_matched_terms


def retry_priority(failed_terms: list[dict]) -> str:
    priorities = {str(x.get("priority") or "").lower() for x in failed_terms}
    if "high" in priorities:
        return "high"
    if failed_terms:
        return "medium"
    return "low"


def main() -> None:
    ap = argparse.ArgumentParser(description="Build retry_repair sample pool from TCR output.")
    ap.add_argument("--input", required=True, help="Annotated TCR JSONL from evaluation/tcr_check.py or evaluation/check_tcr.py.")
    ap.add_argument("--output", required=True, help="Retry pool JSONL output.")
    ap.add_argument("--include-need-review", action="store_true")
    args = ap.parse_args()

    rows = read_jsonl(args.input)
    out = []
    for idx, row in enumerate(rows, 1):
        failed_terms = row.get("failed_terms") or []
        retry_needed = bool(row.get("retry_needed"))
        if not retry_needed and not (args.include_need_review and failed_terms):
            continue
        source_text = pick_first(row, ["source_text", "text", "src", "source"])
        current_translation = pick_first(row, ["new_translation", "mt_text", "translation", "hypothesis", "translated_text"])
        matched_terms = get_matched_terms(row) or row.get("matched_terms") or []
        out.append({
            "sample_id": row.get("sample_id") or row_key(row, idx),
            "source_lang": row.get("source_lang") or row.get("lang") or "",
            "target_lang": row.get("target_lang") or "zh",
            "source_text": source_text,
            "current_translation": current_translation,
            "failed_terms": failed_terms,
            "required_target_terms": row.get("required_target_terms") or [],
            "prompt_mode": classify_sample(source_text, matched_terms, retry_needed=True),
            "retry_needed": True,
            "retry_priority": retry_priority(failed_terms),
            "retry_count": int(row.get("retry_count") or 0) + 1,
            "note": "generated_from_tcr_failure",
        })

    write_jsonl(args.output, out)
    print(json.dumps({"input": args.input, "output": args.output, "retry_rows": len(out)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
