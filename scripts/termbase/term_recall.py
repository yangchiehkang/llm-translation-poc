#!/usr/bin/env python3
# 术语处理脚本：对评测样本做术语召回，并生成 Prompt 实验输入。
# 本地只生成样本与 Prompt 字段，不执行翻译、TCR、XCOMET 或 retry。

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.io_utils import (
    ensure_parent,
    limit_rows,
    pick_first,
    read_jsonl,
    resolve_path,
    row_key,
    write_jsonl,
)
from scripts.common.lang import infer_lang_from_path, normalize_lang
from scripts.common.prompting import (
    GRADED_PROMPT_MODES,
    build_prompt_text,
    classify_sample,
    route_prompt_mode,
)
from scripts.common.termbase import (
    count_core_high,
    hard_required_terms,
    load_termbase,
    match_terms,
    required_target_terms,
    review_terms as collect_review_terms,
    soft_terms as collect_soft_terms,
)

TERMBASE_VERSION_DEFAULT = "termbase_v1"
EXPERIMENT_GROUPS = ["no_term_baseline", "term_baseline", "graded_prompt"]

OUTPUT_FIELDS = [
    "sample_id",
    "document_id",
    "language_pair",
    "source_lang",
    "target_lang",
    "source_text",
    "source_char_count",
    "section_no",
    "segment_type",
    "dataset_base_version",
    "split_name",
    "experiment_group",
    "prompt_strategy",
    "prompt_mode",
    "prompt_text",
    "uses_terms",
    "uses_required_target_terms",
    "uses_prompt_routing",
    "matched_terms",
    "hard_required_terms",
    "review_terms",
    "soft_terms",
    "required_target_terms",
    "matched_high_count",
    "matched_total_count",
    "termbase_version",
    "prompt_route_reason",
    "route_features",
]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _ordered_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in OUTPUT_FIELDS:
        if field in row:
            out[field] = row[field]
    for key, value in row.items():
        if key not in out:
            out[key] = value
    return out


def _load_recall_terms(
    cache: dict[tuple[str, str], list[dict[str, Any]]],
    termbase_path: str,
    source_lang: str,
    target_lang: str,
) -> list[dict[str, Any]]:
    key = (source_lang, target_lang)
    if key not in cache:
        rows = load_termbase(termbase_path, source_lang=source_lang, target_lang=target_lang, active_status=None)
        cache[key] = [row for row in rows if str(row.get("status") or "active").lower() != "inactive"]
    return cache[key]


def _annotate_terms(
    row: dict[str, Any],
    idx: int,
    input_path: str,
    term_cache: dict[tuple[str, str], list[dict[str, Any]]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    fallback_lang = normalize_lang(args.source_lang) or infer_lang_from_path(input_path)
    src_lang = normalize_lang(
        args.source_lang
        or row.get("source_lang")
        or row.get("src_lang_code")
        or row.get("lang")
        or fallback_lang
    )
    if not src_lang:
        raise ValueError(f"Cannot determine source language for row {idx}")
    target_lang = normalize_lang(row.get("target_lang") or args.target_lang)
    source_text = pick_first(row, ["source_text", "text", "src", "source"])
    source_char_count = _as_int(row.get("source_char_count"), len(source_text))
    terms = _load_recall_terms(term_cache, args.termbase, src_lang, target_lang)
    matched = match_terms(source_text, terms)
    hard_terms = hard_required_terms(matched)
    review_terms = collect_review_terms(matched)
    soft_terms = collect_soft_terms(matched)
    required_targets = required_target_terms(matched)
    split_name = row.get("split_name") or Path(input_path).parent.name

    out = dict(row)
    out.update({
        "sample_id": row.get("sample_id") or row_key(row, idx),
        "document_id": row.get("document_id"),
        "language_pair": row.get("language_pair") or f"{src_lang}-{target_lang}",
        "source_lang": src_lang,
        "target_lang": target_lang,
        "source_text": source_text,
        "source_char_count": source_char_count,
        "section_no": row.get("section_no"),
        "segment_type": row.get("segment_type") or "",
        "dataset_base_version": row.get("dataset_base_version") or "",
        "split_name": split_name,
        "matched_terms": matched,
        "hard_required_terms": hard_terms,
        "review_terms": review_terms,
        "soft_terms": soft_terms,
        "required_target_terms": required_targets,
        "matched_high_count": len(hard_terms),
        "matched_total_count": len(matched),
        "termbase_version": args.termbase_version,
    })
    return out


def _make_no_term_row(base: dict[str, Any]) -> dict[str, Any]:
    row = dict(base)
    row.update({
        "experiment_group": "no_term_baseline",
        "prompt_strategy": "no_term_general",
        "prompt_mode": "general_no_terms",
        "prompt_text": build_prompt_text(
            source_text=base["source_text"],
            source_lang=base["source_lang"],
            target_lang=base["target_lang"],
            experiment_group="no_term_baseline",
            prompt_mode="general_no_terms",
        ),
        "uses_terms": False,
        "uses_required_target_terms": False,
        "uses_prompt_routing": False,
    })
    row.pop("prompt_route_reason", None)
    row.pop("route_features", None)
    return _ordered_row(row)


def _make_term_baseline_row(base: dict[str, Any]) -> dict[str, Any]:
    row = dict(base)
    row.update({
        "experiment_group": "term_baseline",
        "prompt_strategy": "term_general",
        "prompt_mode": "general_with_terms",
        "prompt_text": build_prompt_text(
            source_text=base["source_text"],
            source_lang=base["source_lang"],
            target_lang=base["target_lang"],
            experiment_group="term_baseline",
            prompt_mode="general_with_terms",
            required_targets=base["required_target_terms"],
            review_terms=base["review_terms"],
            soft_terms=base["soft_terms"],
        ),
        "uses_terms": True,
        "uses_required_target_terms": True,
        "uses_prompt_routing": False,
    })
    row.pop("prompt_route_reason", None)
    row.pop("route_features", None)
    return _ordered_row(row)


def _make_graded_row(base: dict[str, Any]) -> dict[str, Any]:
    prompt_mode, reason, features = route_prompt_mode(
        source_text=base["source_text"],
        matched_terms=base["matched_terms"],
        source_char_count=base["source_char_count"],
        segment_type=base.get("segment_type"),
        section_no=base.get("section_no"),
        required_targets=base["required_target_terms"],
    )
    if prompt_mode not in GRADED_PROMPT_MODES:
        prompt_mode = "natural_legal"
        reason = "natural_legal: fallback because route returned non-first-translation mode"
    row = dict(base)
    row.update({
        "experiment_group": "graded_prompt",
        "prompt_strategy": "graded",
        "prompt_mode": prompt_mode,
        "prompt_text": build_prompt_text(
            source_text=base["source_text"],
            source_lang=base["source_lang"],
            target_lang=base["target_lang"],
            experiment_group="graded_prompt",
            prompt_mode=prompt_mode,
            required_targets=base["required_target_terms"],
            review_terms=base["review_terms"],
            soft_terms=base["soft_terms"],
        ),
        "uses_terms": True,
        "uses_required_target_terms": True,
        "uses_prompt_routing": True,
        "prompt_route_reason": reason,
        "route_features": features,
    })
    return _ordered_row(row)


def _counter_dict(counter: Counter) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter, key=lambda x: str(x))}


def _write_summary(
    output_dir: Path,
    input_path: str,
    termbase_path: str,
    annotated_rows: list[dict[str, Any]],
    experiment_rows: dict[str, list[dict[str, Any]]],
    termbase_version: str,
) -> dict[str, Any]:
    split_name = annotated_rows[0]["split_name"] if annotated_rows else Path(input_path).parent.name
    language_counts = Counter(row["source_lang"] for row in annotated_rows)
    high_dist_by_lang: dict[str, Counter] = defaultdict(Counter)
    for row in annotated_rows:
        high_dist_by_lang[row["source_lang"]][row["matched_high_count"]] += 1

    graded_modes = Counter(row["prompt_mode"] for row in experiment_rows["graded_prompt"])
    sample_ids = {group: [row["sample_id"] for row in rows] for group, rows in experiment_rows.items()}
    source_texts = {group: [row["source_text"] for row in rows] for group, rows in experiment_rows.items()}
    required_terms = {group: [row["required_target_terms"] for row in rows] for group, rows in experiment_rows.items()}
    first_group = EXPERIMENT_GROUPS[0]

    summary = {
        "split_name": split_name,
        "total_samples": len(annotated_rows),
        "termbase_version": termbase_version,
        "termbase_path": termbase_path,
        "experiment_groups": EXPERIMENT_GROUPS,
        "group_sample_counts": {group: len(rows) for group, rows in experiment_rows.items()},
        "group_prompt_strategy": {
            "no_term_baseline": "no_term_general",
            "term_baseline": "term_general",
            "graded_prompt": "graded",
        },
        "no_term_baseline_no_term_injection": True,
        "term_baseline_injects_terms_without_routing": True,
        "graded_prompt_uses_routing": True,
        "graded_prompt_mode_distribution": _counter_dict(graded_modes),
        "language_counts": _counter_dict(language_counts),
        "matched_high_count_distribution_by_lang": {
            lang: _counter_dict(counter) for lang, counter in sorted(high_dist_by_lang.items())
        },
        "required_target_terms_nonempty_samples": sum(1 for row in annotated_rows if row["required_target_terms"]),
        "fairness": {
            "same_source_text": all(source_texts[group] == source_texts[first_group] for group in EXPERIMENT_GROUPS),
            "same_sample_ids": all(sample_ids[group] == sample_ids[first_group] for group in EXPERIMENT_GROUPS),
            "same_termbase": True,
            "same_required_target_terms_field": all(required_terms[group] == required_terms[first_group] for group in EXPERIMENT_GROUPS),
            "future_model_parameter_note": "后续真实翻译应使用同一模型和同一采样参数。",
        },
        "retry_repair_template_defined": True,
        "retry_samples_generated": False,
        "translation_executed": False,
        "tcr_executed": False,
        "xcomet_executed": False,
        "generated_files": {
            "no_term_baseline": str(output_dir / "no_term_baseline.jsonl"),
            "term_baseline": str(output_dir / "term_baseline.jsonl"),
            "graded_prompt": str(output_dir / "graded_prompt.jsonl"),
            "summary_md": str(output_dir / "prompt_design_summary.md"),
            "summary_json": str(output_dir / "prompt_design_summary.json"),
        },
    }

    summary_json = ensure_parent(output_dir / "prompt_design_summary.json")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    mode_lines = "\n".join(
        f"- {mode}: {count}" for mode, count in summary["graded_prompt_mode_distribution"].items()
    ) or "- 无"
    lang_lines = "\n".join(f"- {lang}: {count}" for lang, count in summary["language_counts"].items()) or "- 无"
    group_lines = "\n".join(
        f"- {group}: {summary['group_sample_counts'][group]} samples, strategy={summary['group_prompt_strategy'][group]}"
        for group in EXPERIMENT_GROUPS
    )
    high_lines = "\n".join(
        f"- {lang}: {dict(dist)}" for lang, dist in summary["matched_high_count_distribution_by_lang"].items()
    ) or "- 无"
    md = f"""# Prompt Design Summary

## Split
- split_name: {summary['split_name']}
- total_samples: {summary['total_samples']}
- termbase_version: {summary['termbase_version']}
- termbase_path: {summary['termbase_path']}

## Experiment Groups
{group_lines}

## Strategy Checks
- no_term_baseline 不注入术语: {summary['no_term_baseline_no_term_injection']}
- term_baseline 注入术语但不分级: {summary['term_baseline_injects_terms_without_routing']}
- graded_prompt 使用分级路由: {summary['graded_prompt_uses_routing']}
- retry_repair 模板已定义但未执行: {summary['retry_repair_template_defined']}

## Graded Prompt Mode Distribution
{mode_lines}

## Language Counts
{lang_lines}

## Matched High Count Distribution By Language
{high_lines}

## Required Terms
- required_target_terms 非空样本数: {summary['required_target_terms_nonempty_samples']}
- required_target_terms 只来自 priority=high 且 status=active 的术语。
- status=review 可召回但不进入 required_target_terms。
- status=inactive 不参与召回。

## Fairness
- 同一批 source_text: {summary['fairness']['same_source_text']}
- 同一批 sample_id: {summary['fairness']['same_sample_ids']}
- 同一术语库: {summary['fairness']['same_termbase']}
- 同一 required_target_terms 字段: {summary['fairness']['same_required_target_terms_field']}
- 后续应使用同一模型和同一参数。

## Not Executed In This Stage
- 未执行真实翻译。
- 未执行 TCR。
- 未运行 XCOMET。
- 未生成 retry 样本。
"""
    summary_md = ensure_parent(output_dir / "prompt_design_summary.md")
    summary_md.write_text(md, encoding="utf-8")
    return summary


def run_recall(args: argparse.Namespace) -> None:
    if not args.output:
        raise ValueError("--output is required when --mode recall")
    rows = limit_rows(read_jsonl(args.input), args.limit)
    term_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    out = []
    for idx, row in enumerate(rows, 1):
        annotated = _annotate_terms(row, idx, args.input, term_cache, args)
        annotated["matched_term_count"] = annotated["matched_total_count"]
        annotated["matched_core_high_count"] = count_core_high(annotated["matched_terms"])
        annotated["prompt_mode"] = classify_sample(
            annotated["source_text"],
            annotated["matched_terms"],
            source_char_count=annotated["source_char_count"],
            segment_type=annotated.get("segment_type"),
            section_no=annotated.get("section_no"),
        )
        out.append(annotated)

    write_jsonl(args.output, out)
    print(json.dumps({
        "input": args.input,
        "output": args.output,
        "rows": len(out),
        "rows_with_terms": sum(1 for row in out if row.get("matched_total_count", 0) > 0),
        "required_terms": sum(len(row.get("required_target_terms") or []) for row in out),
    }, ensure_ascii=False, indent=2))


def build_prompt_experiment_inputs(args: argparse.Namespace) -> None:
    if not args.output_dir:
        raise ValueError("--output-dir is required when --mode build_prompt_experiment_inputs")
    rows = limit_rows(read_jsonl(args.input), args.limit)
    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    term_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    annotated_rows = [
        _annotate_terms(row, idx, args.input, term_cache, args)
        for idx, row in enumerate(rows, 1)
    ]
    experiment_rows = {
        "no_term_baseline": [_make_no_term_row(row) for row in annotated_rows],
        "term_baseline": [_make_term_baseline_row(row) for row in annotated_rows],
        "graded_prompt": [_make_graded_row(row) for row in annotated_rows],
    }

    for group, group_rows in experiment_rows.items():
        write_jsonl(output_dir / f"{group}.jsonl", group_rows)

    summary = _write_summary(
        output_dir=output_dir,
        input_path=args.input,
        termbase_path=args.termbase,
        annotated_rows=annotated_rows,
        experiment_rows=experiment_rows,
        termbase_version=args.termbase_version,
    )
    print(json.dumps({
        "input": args.input,
        "output_dir": str(output_dir),
        "rows": len(annotated_rows),
        "group_sample_counts": summary["group_sample_counts"],
        "graded_prompt_mode_distribution": summary["graded_prompt_mode_distribution"],
        "required_target_terms_nonempty_samples": summary["required_target_terms_nonempty_samples"],
    }, ensure_ascii=False, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description="术语召回、Prompt 路由和 Prompt 实验输入生成。")
    ap.add_argument("--mode", default="recall", choices=["recall", "build_prompt_experiment_inputs"])
    ap.add_argument("--input", required=True, help="Input JSONL file.")
    ap.add_argument("--output", default="", help="Output JSONL file for --mode recall.")
    ap.add_argument("--output-dir", default="", help="Output directory for --mode build_prompt_experiment_inputs.")
    ap.add_argument("--termbase", default="termbase/auto_regulation_terms_v1.csv")
    ap.add_argument("--termbase-version", default=TERMBASE_VERSION_DEFAULT)
    ap.add_argument("--source-lang", default="", help="Source language code. If empty, infer from row or file name.")
    ap.add_argument("--target-lang", default="zh")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.mode == "recall":
        run_recall(args)
    elif args.mode == "build_prompt_experiment_inputs":
        build_prompt_experiment_inputs(args)
    else:
        raise ValueError(f"Unsupported mode: {args.mode}")


if __name__ == "__main__":
    main()
