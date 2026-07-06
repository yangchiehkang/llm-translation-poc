#!/usr/bin/env python3
# 质量评估脚本：检查译文是否命中 hard required terms，计算样本级和批次级 TCR。
# 运行位置：本地；输出 failed_terms 和 retry_needed，作为定向重试的输入。

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.io_utils import read_jsonl, write_jsonl, pick_first, row_key, limit_rows, ensure_parent
from scripts.common.lang import infer_lang_from_path, normalize_lang
from scripts.common.termbase import (
    load_termbase,
    match_terms,
    get_matched_terms,
    hard_required_terms,
    target_present,
    required_target_terms,
)


def classify_failure(translation: str, term: dict) -> str:
    target = str(term.get("target_term") or "")
    if not translation.strip():
        return "missing_translation"
    if target and any(ch in translation for ch in target[:1]):
        return "partial"
    return "missing"


def main() -> None:
    ap = argparse.ArgumentParser(description="TCR 硬校验。")
    ap.add_argument("--input", required=True, help="Translated JSONL file.")
    ap.add_argument("--output", required=True, help="Annotated JSONL output.")
    ap.add_argument("--summary", default="", help="Summary JSON output. Optional.")
    ap.add_argument("--termbase", default="termbase/auto_regulation_terms_v1.csv")
    ap.add_argument("--source-lang", default="")
    ap.add_argument("--target-lang", default="zh")
    ap.add_argument("--scope", choices=["hard", "all"], default="hard")
    ap.add_argument("--allow-alias", action="store_true", help="Diagnostic only. Do not use for hard acceptance.")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = limit_rows(read_jsonl(args.input), args.limit)
    fallback_lang = normalize_lang(args.source_lang) or infer_lang_from_path(args.input)
    cache: dict[str, list[dict]] = {}

    out = []
    total_required = 0
    total_correct = 0
    rows_with_required = 0
    failed_rows = 0

    for idx, row in enumerate(rows, 1):
        src_lang = normalize_lang(
            args.source_lang
            or row.get("source_lang")
            or row.get("src_lang_code")
            or row.get("lang")
            or fallback_lang
        )
        if not src_lang:
            raise ValueError(f"Cannot determine source language for row {idx}")
        source_text = pick_first(row, ["source_text", "text", "src", "source"])
        translation = pick_first(row, ["new_translation", "mt_text", "translation", "hypothesis", "translated_text"])
        matched = get_matched_terms(row)
        if not matched:
            if src_lang not in cache:
                cache[src_lang] = load_termbase(args.termbase, source_lang=src_lang, target_lang=args.target_lang)
            matched = match_terms(source_text, cache[src_lang])

        required = hard_required_terms(matched, scope=args.scope)
        term_results = []
        correct = 0
        failed_terms = []
        for term in required:
            ok = target_present(translation, term, allow_alias=args.allow_alias)
            if ok:
                correct += 1
            else:
                failed = {
                    "term_id": term.get("term_id", ""),
                    "source_term": term.get("source_term", ""),
                    "target_term": term.get("target_term", ""),
                    "priority": term.get("priority", ""),
                    "error_type": classify_failure(translation, term),
                }
                failed_terms.append(failed)
            term_results.append({
                "term_id": term.get("term_id", ""),
                "source_term": term.get("source_term", ""),
                "target_term": term.get("target_term", ""),
                "passed": ok,
            })

        required_count = len(required)
        sample_tcr = 1.0 if required_count == 0 else correct / required_count
        status = "pass" if required_count == 0 or correct == required_count else "fail"
        retry_needed = status == "fail" and any(f["error_type"] in {"missing", "partial", "missing_translation"} for f in failed_terms)

        total_required += required_count
        total_correct += correct
        if required_count:
            rows_with_required += 1
        if status == "fail":
            failed_rows += 1

        new_row = dict(row)
        new_row.setdefault("sample_id", row_key(row, idx))
        new_row["source_lang"] = src_lang
        new_row["target_lang"] = normalize_lang(args.target_lang)
        new_row["source_text"] = source_text
        new_row["new_translation"] = translation
        new_row["matched_terms"] = matched
        new_row["required_target_terms"] = required_target_terms(matched, scope=args.scope)
        new_row["term_results"] = term_results
        new_row["failed_terms"] = failed_terms
        new_row["required_term_count"] = required_count
        new_row["correct_term_count"] = correct
        new_row["tcr_after"] = round(sample_tcr, 6)
        new_row["final_status"] = status
        new_row["retry_needed"] = retry_needed
        out.append(new_row)

    batch_tcr = 1.0 if total_required == 0 else total_correct / total_required
    summary = {
        "input": args.input,
        "output": args.output,
        "scope": args.scope,
        "allow_alias": args.allow_alias,
        "rows": len(out),
        "rows_with_required_terms": rows_with_required,
        "failed_rows": failed_rows,
        "required_terms": total_required,
        "correct_terms": total_correct,
        "batch_tcr": round(batch_tcr, 6),
    }
    write_jsonl(args.output, out)
    if args.summary:
        p = ensure_parent(args.summary)
        p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
