#!/usr/bin/env python3
"""Summarize XCOMET-QE and XCOMET-DA/COMET score JSONL files."""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.io_utils import ensure_parent, read_jsonl, resolve_path
from scripts.common.text_utils import utc_now


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize XCOMET score outputs.")
    parser.add_argument(
        "--inputs",
        nargs="*",
        default=[
            "outputs/evaluation/xcomet/qe/*.jsonl",
            "outputs/evaluation/xcomet/da/*.jsonl",
        ],
        help="Input JSONL files or glob patterns.",
    )
    parser.add_argument("--output", default="outputs/evaluation/xcomet/summary/xcomet_summary.md")
    return parser.parse_args()


def expand_inputs(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        resolved_pattern = str(resolve_path(pattern))
        matches = [Path(match) for match in glob.glob(resolved_pattern)]
        if not matches and Path(resolved_pattern).exists():
            matches = [Path(resolved_pattern)]
        for path in sorted(matches):
            if path not in seen and path.is_file():
                seen.add(path)
                paths.append(path)
    return paths


def as_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def fmt_number(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("split") or ""),
            str(row.get("mode") or ""),
            str(row.get("system_or_group") or ""),
            str(row.get("translation_stage") or ""),
        )
        groups[key].append(row)

    summary_rows: list[dict[str, Any]] = []
    for (split, mode, group, stage), group_rows in sorted(groups.items()):
        scores = [
            score
            for score in (as_number(row.get("score")) for row in group_rows if row.get("status") == "success")
            if score is not None
        ]
        success_count = sum(1 for row in group_rows if row.get("status") == "success")
        failed_count = sum(1 for row in group_rows if row.get("status") == "failed")
        summary_rows.append(
            {
                "split": split,
                "mode": mode,
                "system_or_group": group,
                "translation_stage": stage,
                "count": len(group_rows),
                "success_count": success_count,
                "failed_count": failed_count,
                "avg_score": statistics.fmean(scores) if scores else None,
                "median_score": statistics.median(scores) if scores else None,
                "std_score": statistics.pstdev(scores) if len(scores) > 1 else 0.0 if scores else None,
            }
        )
    return summary_rows


def write_markdown(path: Path, summary_rows: list[dict[str, Any]], inputs: list[Path]) -> None:
    lines = [
        "# XCOMET Summary",
        "",
        f"Generated at: `{utc_now()}`",
        "",
        "## Inputs",
        "",
    ]
    if inputs:
        lines.extend(f"- `{display_path(input_path)}`" for input_path in inputs)
    else:
        lines.append("- No input files found.")
    lines.extend(
        [
            "",
            "## Aggregates",
            "",
            "| split | mode | system_or_group | translation_stage | count | success_count | failed_count | avg_score | median_score | std_score |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in summary_rows:
        lines.append(
            "| {split} | {mode} | {system_or_group} | {translation_stage} | {count} | {success_count} | "
            "{failed_count} | {avg_score} | {median_score} | {std_score} |".format(
                split=row["split"],
                mode=row["mode"],
                system_or_group=row["system_or_group"],
                translation_stage=row["translation_stage"],
                count=row["count"],
                success_count=row["success_count"],
                failed_count=row["failed_count"],
                avg_score=fmt_number(row["avg_score"]),
                median_score=fmt_number(row["median_score"]),
                std_score=fmt_number(row["std_score"]),
            )
        )
    output = ensure_parent(path)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    input_paths = expand_inputs(args.inputs)
    rows: list[dict[str, Any]] = []
    for path in input_paths:
        rows.extend(read_jsonl(path))
    summary_rows = summarize(rows)
    output_path = resolve_path(args.output)
    write_markdown(output_path, summary_rows, input_paths)
    print(
        json.dumps(
            {
                "inputs": [str(path) for path in input_paths],
                "rows": len(rows),
                "groups": len(summary_rows),
                "output": str(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
