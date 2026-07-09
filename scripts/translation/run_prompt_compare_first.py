#!/usr/bin/env python3
# Run first-pass Qwen-Max translations for prompt experiment inputs.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.dashscope_client import call_dashscope_generation, sanitize_error as sanitize_dashscope_error
from scripts.common.io_utils import read_jsonl, append_jsonl, resolve_path
from scripts.common.text_utils import utc_now

GROUPS = ("no_term_baseline", "term_baseline", "graded_prompt")


def prompt_hash(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


def call_qwenmax(
    prompt_text: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    max_api_retries: int,
    sleep_between_retries: float,
) -> tuple[str, int]:
    messages = [
        {
            "role": "system",
            "content": "你是法规和标准文本翻译引擎。只输出译文，不输出解释、分析、Markdown 或额外说明。",
        },
        {"role": "user", "content": prompt_text},
    ]
    return call_dashscope_generation(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_attempts=max_api_retries + 1,
        sleep_seconds=sleep_between_retries,
        retry_log_prefix="[API_RETRY]",
        failure_message="Qwen-Max call failed after API retries",
    )


def resume_state(path: Path) -> tuple[set[str], dict[str, int]]:
    success_ids: set[str] = set()
    failed_counts: dict[str, int] = {}
    if not path.exists():
        return success_ids, failed_counts
    for row in read_jsonl(path):
        sample_id = str(row.get("sample_id") or "")
        if not sample_id:
            continue
        if row.get("status") == "success" and row.get("hypothesis"):
            success_ids.add(sample_id)
        else:
            failed_counts[sample_id] = failed_counts.get(sample_id, 0) + 1
    return success_ids, failed_counts


def output_row(
    row: dict[str, Any],
    *,
    group: str,
    args: argparse.Namespace,
    hypothesis: str,
    status: str,
    error_message: str,
    latency_ms: int,
    retry_count: int,
) -> dict[str, Any]:
    prompt_text = str(row.get("prompt_text") or "")
    source_text = str(row.get("source_text") or "")
    return {
        "sample_id": row.get("sample_id"),
        "document_id": row.get("document_id"),
        "language_pair": row.get("language_pair"),
        "source_lang": row.get("source_lang"),
        "target_lang": row.get("target_lang"),
        "source_text": source_text,
        "hypothesis": hypothesis,
        "experiment_group": group,
        "prompt_strategy": row.get("prompt_strategy"),
        "prompt_mode": row.get("prompt_mode"),
        "prompt_hash": row.get("prompt_hash") or prompt_hash(prompt_text),
        "model_name": args.model,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "termbase_version": row.get("termbase_version"),
        "required_target_terms": row.get("required_target_terms") or [],
        "matched_terms": row.get("matched_terms") or [],
        "translation_stage": args.translation_stage,
        "status": status,
        "error_message": error_message,
        "latency_ms": latency_ms,
        "input_char_count": len(prompt_text),
        "output_char_count": len(hypothesis),
        "retry_count": retry_count,
        "created_at": utc_now(),
    }


def translate_group(group: str, input_path: Path, output_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    rows = read_jsonl(input_path)
    expected_count = len(rows)
    if args.limit > 0:
        rows = rows[: args.limit]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not args.resume:
        output_path.unlink()

    success_ids, failed_counts = resume_state(output_path) if args.resume else (set(), {})
    completed = 0
    skipped = 0
    failed = 0
    latencies: list[int] = []

    for index, row in enumerate(rows, 1):
        sample_id = str(row.get("sample_id") or f"row_{index}")
        if sample_id in success_ids:
            skipped += 1
            continue
        if failed_counts.get(sample_id, 0) >= args.failed_retry_attempts:
            skipped += 1
            continue

        prompt_text = str(row.get("prompt_text") or "")
        start = time.monotonic()
        hypothesis = ""
        status = "failed"
        error_message = ""
        retry_count = 0

        try:
            if not prompt_text:
                raise ValueError("missing prompt_text")
            if args.dry_run:
                hypothesis = f"[DRY_RUN] {row.get('source_text') or ''}".strip()
                retry_count = 0
            else:
                hypothesis, retry_count = call_qwenmax(
                    prompt_text,
                    args.model,
                    args.temperature,
                    args.max_tokens,
                    args.timeout,
                    args.max_api_retries,
                    args.sleep_between_retries,
                )
            if not hypothesis:
                raise RuntimeError("empty hypothesis")
            status = "success"
            completed += 1
        except Exception as exc:
            error_message = sanitize_dashscope_error(exc)
            failed += 1
        latency_ms = int((time.monotonic() - start) * 1000)
        if status == "success":
            latencies.append(latency_ms)

        append_jsonl(
            output_path,
            output_row(
                row,
                group=group,
                args=args,
                hypothesis=hypothesis,
                status=status,
                error_message=error_message,
                latency_ms=latency_ms,
                retry_count=retry_count,
            ),
        )

        print(
            json.dumps(
                {
                    "group": group,
                    "index": index,
                    "sample_id": sample_id,
                    "status": status,
                    "latency_ms": latency_ms,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if args.sleep > 0:
            time.sleep(args.sleep)

    return {
        "group": group,
        "input_file": str(input_path),
        "output_file": str(output_path),
        "expected_count": expected_count,
        "processed_count": len(rows),
        "success_count": completed,
        "failed_count": failed,
        "skipped_count": skipped,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
    }


def validate_summary(output_files: dict[str, Path]) -> dict[str, Any]:
    sample_sets: dict[str, set[str]] = {}
    counts: dict[str, dict[str, int]] = {}
    for group, path in output_files.items():
        rows = read_jsonl(path) if path.exists() else []
        sample_sets[group] = {str(row.get("sample_id")) for row in rows if row.get("status") == "success"}
        counts[group] = {
            "rows": len(rows),
            "success": sum(1 for row in rows if row.get("status") == "success" and row.get("hypothesis")),
            "failed": sum(1 for row in rows if row.get("status") != "success"),
            "first_stage": sum(1 for row in rows if row.get("translation_stage") == "first"),
        }
    all_sets = list(sample_sets.values())
    return {
        "counts": counts,
        "success_sample_sets_equal": all(sample_set == all_sets[0] for sample_set in all_sets[1:]) if all_sets else True,
    }


def write_summary(args: argparse.Namespace, group_results: list[dict[str, Any]], output_files: dict[str, Path], started_at: str, finished_at: str) -> None:
    if not args.summary:
        return

    summary_json_path = resolve_path(args.summary)
    summary_md_path = summary_json_path.with_suffix(".md")
    validation = validate_summary(output_files)
    summary = {
        "split_name": args.split_name,
        "translation_stage": args.translation_stage,
        "model_name": args.model,
        "model_backend": args.model_backend,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "input_files": {item["group"]: item["input_file"] for item in group_results},
        "output_files": {group: str(path) for group, path in output_files.items()},
        "expected_count_by_group": {item["group"]: item["expected_count"] for item in group_results},
        "success_count_by_group": {item["group"]: item["success_count"] for item in group_results},
        "failed_count_by_group": {item["group"]: item["failed_count"] for item in group_results},
        "skipped_count_by_group": {item["group"]: item["skipped_count"] for item in group_results},
        "avg_latency_ms_by_group": {item["group"]: item["avg_latency_ms"] for item in group_results},
        "started_at": started_at,
        "finished_at": finished_at,
        "notes": [
            "本阶段只执行首译。",
            "未执行 retry_repair。",
            "未执行 TCR。",
            "未执行 XCOMET。",
            "未运行其他 split。",
        ],
        "validation": validation,
    }

    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Translation Run Summary",
        "",
        f"- split_name: {args.split_name}",
        f"- translation_stage: {args.translation_stage}",
        f"- model_name: {args.model}",
        f"- model_backend: {args.model_backend}",
        f"- temperature: {args.temperature}",
        f"- max_tokens: {args.max_tokens}",
        f"- started_at: {started_at}",
        f"- finished_at: {finished_at}",
        "",
        "## Counts",
        "",
        "| group | expected | success | failed | skipped | avg_latency_ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in group_results:
        lines.append(
            f"| {item['group']} | {item['expected_count']} | {item['success_count']} | "
            f"{item['failed_count']} | {item['skipped_count']} | {item['avg_latency_ms']} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- 本阶段只执行首译。",
            "- 未执行 retry_repair。",
            "- 未执行 TCR。",
            "- 未执行 XCOMET。",
            "- 未运行其他 split。",
        ]
    )
    summary_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run first translations from prompt_text experiment inputs.")
    ap.add_argument("--input-dir", default="outputs/experiment_inputs/source_only_300_by_lang")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--groups", nargs="+", default=list(GROUPS), choices=GROUPS)
    ap.add_argument("--split-name", default="source_only_300_by_lang")
    ap.add_argument("--translation-stage", default="first")
    ap.add_argument("--output-suffix", default="first_translations")
    ap.add_argument("--summary", default="")
    ap.add_argument("--model", default="qwen-max")
    ap.add_argument("--model-backend", default="dashscope_qwenmax")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--max-api-retries", type=int, default=2)
    ap.add_argument("--failed-retry-attempts", type=int, default=2)
    ap.add_argument("--sleep-between-retries", type=float, default=1.5)
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    api_key = os.getenv("DASHSCOPE_API_KEY") or ""
    if not args.dry_run:
        if not api_key:
            raise RuntimeError("Missing environment variable DASHSCOPE_API_KEY on server.")
        if not api_key.isascii():
            raise RuntimeError("DASHSCOPE_API_KEY contains non-ASCII characters; fix the server secret before running.")

    started_at = utc_now()
    input_dir = resolve_path(args.input_dir)
    output_dir = resolve_path(args.output_dir)
    output_files: dict[str, Path] = {}
    group_results: list[dict[str, Any]] = []

    for group in args.groups:
        input_path = input_dir / f"{group}.jsonl"
        output_path = output_dir / f"{group}_{args.output_suffix}.jsonl"
        output_files[group] = output_path
        print(f"[TRANSLATE] group={group} input={input_path} output={output_path}", flush=True)
        group_results.append(translate_group(group, input_path, output_path, args))

    finished_at = utc_now()
    write_summary(args, group_results, output_files, started_at, finished_at)
    print(json.dumps({"files": group_results}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
