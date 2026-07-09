#!/usr/bin/env python3
"""Build standard XCOMET-DA/COMET input JSONL files."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.io_utils import ensure_parent, pick_first, read_jsonl, resolve_path, write_jsonl
from scripts.common.text_utils import clean_text

SOURCE_ONLY_SPLIT = "source_only_300_by_lang"
REFERENCE_WITH_REF_SPLIT = "reference_with_ref_300_by_lang"
REFERENCE_SPLIT_BY_TRANSLATION_SPLIT = {
    SOURCE_ONLY_SPLIT: REFERENCE_WITH_REF_SPLIT,
}

DEFAULT_SPLITS = [SOURCE_ONLY_SPLIT]
DEFAULT_GROUPS = ["no_term_baseline", "term_baseline", "graded_prompt"]
DEFAULT_STAGES = ["first_pass", "final"]
DA_FIELD_NAMES = [
    "ref_text",
    "alignment_confidence",
    "alignment_method",
    "page_ref",
    "order_ref",
    "use_for_da",
    "ref_source",
    "reference_source",
    "ref_type",
    "is_summary_ref",
    "ref_is_summary",
    "is_machine_ref",
    "machine_ref",
    "ref_is_machine_translation",
    "ref_confirmed",
    "human_verified",
    "source_ref_aligned",
    "ref_aligned",
    "is_aligned",
]
CONFIDENCE_LABELS = {
    "high": 1.0,
    "exact": 1.0,
    "exact_section": 1.0,
    "manual": 1.0,
    "verified": 1.0,
    "medium": 0.5,
    "med": 0.5,
    "low": 0.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build XCOMET DA/COMET input JSONL from existing translation outputs."
    )
    parser.add_argument("--splits", nargs="+", default=DEFAULT_SPLITS)
    parser.add_argument("--groups", nargs="+", default=DEFAULT_GROUPS)
    parser.add_argument("--stages", nargs="+", default=DEFAULT_STAGES)
    parser.add_argument(
        "--reference-split",
        default="",
        help=(
            "Reference split used for ref_text lookup. Defaults to the paired "
            "reference_with_ref_300_by_lang split when scoring source_only_300_by_lang."
        ),
    )
    parser.add_argument("--min-alignment-confidence", type=float, default=0.8)
    parser.add_argument("--output-dir", default="outputs/evaluation/xcomet/inputs")
    parser.add_argument("--dry-run", action="store_true", help="Print counts without writing JSONL files.")
    parser.add_argument("--strict", action="store_true", help="Fail on missing requested inputs or bad required fields.")
    return parser.parse_args()


def normalize_stage(stage: str) -> str:
    aliases = {
        "first": "first_pass",
        "first-pass": "first_pass",
        "first_pass": "first_pass",
        "retry": "retry",
        "retry_tcr": "retry",
        "final": "final",
    }
    normalized = aliases.get(stage.strip().lower())
    if not normalized:
        raise ValueError(f"Unsupported translation stage: {stage}")
    return normalized


def truthy(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "t", "yes", "y", "1"}:
        return True
    if text in {"false", "f", "no", "n", "0"}:
        return False
    return None


def confidence_score(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return CONFIDENCE_LABELS.get(text)


def is_summary_ref(meta: dict[str, Any]) -> bool:
    for name in ["is_summary_ref", "ref_is_summary"]:
        flag = truthy(meta.get(name))
        if flag is not None:
            return flag
    ref_type = clean_text(meta.get("ref_type")).lower()
    return "summary" in ref_type if ref_type else False


def is_unconfirmed_machine_ref(meta: dict[str, Any]) -> bool:
    machine_flag = False
    for name in ["is_machine_ref", "machine_ref", "ref_is_machine_translation"]:
        flag = truthy(meta.get(name))
        if flag is True:
            machine_flag = True
    ref_source = clean_text(pick_first(meta, ["ref_source", "reference_source"])).lower()
    if "machine" in ref_source or ref_source in {"mt", "machine_ref"}:
        machine_flag = True
    if not machine_flag:
        return False
    for name in ["ref_confirmed", "human_verified"]:
        flag = truthy(meta.get(name))
        if flag is True:
            return False
    return True


def is_explicitly_unaligned(meta: dict[str, Any]) -> bool:
    for name in ["source_ref_aligned", "ref_aligned", "is_aligned"]:
        flag = truthy(meta.get(name))
        if flag is False:
            return True
    return False


def first_translation_path(split: str, group: str) -> Path:
    return resolve_path(f"outputs/translations/{split}/first/{group}_first_translations.jsonl")


def retry_translation_path(split: str, group: str) -> Path:
    return resolve_path(f"outputs/translations_retry/{split}/{group}_retry_translations.jsonl")


def final_translation_candidates(split: str, group: str) -> list[Path]:
    return [
        resolve_path(f"outputs/translations_final/{split}/{group}_final_translations.jsonl"),
        resolve_path(f"outputs/translations_final/{split}/final/{group}_final_translations.jsonl"),
        resolve_path(f"outputs/translations_final/{split}/{group}_translations_final.jsonl"),
        resolve_path(f"outputs/translations_final/{split}/final/{group}_translations.jsonl"),
    ]


def read_optional_jsonl(path: Path, errors: list[str], *, strict: bool, label: str) -> list[dict[str, Any]]:
    if path.exists():
        return read_jsonl(path)
    message = f"Missing {label}: {path}"
    if strict:
        errors.append(message)
    else:
        print(f"WARNING: {message}", file=sys.stderr)
    return []


def index_by_sample(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sample_id = clean_text(row.get("sample_id"))
        if sample_id and sample_id not in out:
            out[sample_id] = row
    return out


def project_rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def load_eval_indexes(
    split: str,
    *,
    reference_split: str = "",
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
    all_paths = [
        resolve_path(f"data/eval/splits/{split}/all_samples_source_only.jsonl"),
        resolve_path(f"data/eval/splits/{split}/all_samples_with_reference.jsonl"),
    ]
    all_rows: list[dict[str, Any]] = []
    all_source = ""
    for path in all_paths:
        if path.exists():
            all_rows = read_jsonl(path)
            all_source = project_rel(path)
            break
    all_index = index_by_sample(all_rows)

    resolved_reference_split = reference_split or REFERENCE_SPLIT_BY_TRANSLATION_SPLIT.get(split, split)
    da_paths = [
        resolve_path(f"data/eval/splits/{resolved_reference_split}/all_samples_with_reference.jsonl"),
    ]
    if resolved_reference_split != split:
        da_paths.extend([
            resolve_path(f"data/eval/splits/{split}/all_samples_with_reference.jsonl"),
        ])
    da_rows: list[dict[str, Any]] = []
    da_source = ""
    for path in da_paths:
        if path.exists():
            rows = read_jsonl(path)
            if all_index:
                rows = [row for row in rows if clean_text(row.get("sample_id")) in all_index]
            da_source = project_rel(path)
            for row in rows:
                row.setdefault("_da_source_path", da_source)
            da_rows = rows
            break

    return (
        all_index,
        index_by_sample(da_rows),
        {
            "source_file": all_source,
            "reference_file": da_source,
            "reference_split": resolved_reference_split,
        },
    )


def copy_da_fields(target: dict[str, Any], source: dict[str, Any]) -> None:
    for name in DA_FIELD_NAMES:
        if source.get(name) is not None and source.get(name) != "":
            target[name] = source[name]


def derive_final_rows(split: str, group: str, errors: list[str], *, strict: bool) -> tuple[list[dict[str, Any]], str]:
    first_path = first_translation_path(split, group)
    first_rows = read_optional_jsonl(first_path, errors, strict=strict, label="first-pass translations for final stage")
    if not first_rows:
        return [], "missing"

    retry_path = retry_translation_path(split, group)
    retry_rows = read_jsonl(retry_path) if retry_path.exists() else []
    if not retry_rows:
        print(
            f"WARNING: No retry translations found for derived final stage: {retry_path}; "
            "final rows will match first_pass rows.",
            file=sys.stderr,
        )

    retry_by_sample: dict[str, dict[str, Any]] = {}
    for row in retry_rows:
        sample_id = clean_text(row.get("sample_id"))
        hypothesis = clean_text(row.get("retry_translation"))
        status = clean_text(row.get("status")).lower()
        if sample_id and hypothesis and status == "success":
            retry_by_sample[sample_id] = row

    final_rows: list[dict[str, Any]] = []
    for row in first_rows:
        sample_id = clean_text(row.get("sample_id"))
        out = dict(row)
        out["translation_stage"] = "final"
        out["_xcomet_translation_source"] = "first_pass"
        retry_row = retry_by_sample.get(sample_id)
        if retry_row:
            out["hypothesis"] = retry_row["retry_translation"]
            out["_xcomet_translation_source"] = "retry_overlay"
            copy_da_fields(out, retry_row)
        final_rows.append(out)
    return final_rows, "derived_from_first_pass_plus_retry"


def load_stage_rows(
    split: str,
    group: str,
    stage: str,
    errors: list[str],
    *,
    strict: bool,
) -> tuple[list[dict[str, Any]], str]:
    if stage == "first_pass":
        path = first_translation_path(split, group)
        return read_optional_jsonl(path, errors, strict=strict, label="first-pass translations"), str(
            path.relative_to(PROJECT_ROOT)
        )

    if stage == "retry":
        path = retry_translation_path(split, group)
        return read_optional_jsonl(path, errors, strict=strict, label="retry translations"), str(
            path.relative_to(PROJECT_ROOT)
        )

    for path in final_translation_candidates(split, group):
        if path.exists():
            rows = read_jsonl(path)
            for row in rows:
                row.setdefault("_xcomet_translation_source", "outputs/translations_final")
            return rows, str(path.relative_to(PROJECT_ROOT))

    return derive_final_rows(split, group, errors, strict=strict)


def extract_hypothesis(row: dict[str, Any], stage: str) -> str:
    fields_by_stage = {
        "first_pass": ["hypothesis", "hypothesis_translation", "translation", "translated_text", "mt"],
        "retry": ["retry_translation", "hypothesis", "hypothesis_translation", "translation", "translated_text"],
        "final": ["final_translation", "hypothesis", "hypothesis_translation", "translation", "retry_translation"],
    }
    return clean_text(pick_first(row, fields_by_stage[stage]))


def build_common_record(
    row: dict[str, Any],
    *,
    split: str,
    group: str,
    stage: str,
    all_index: dict[str, dict[str, Any]],
    input_source: str,
) -> tuple[dict[str, Any] | None, str | None]:
    sample_id = clean_text(row.get("sample_id"))
    if not sample_id:
        return None, "missing_sample_id"

    eval_row = all_index.get(sample_id, {})
    source_text = clean_text(pick_first(row, ["source_text", "source", "src"]))
    if not source_text:
        source_text = clean_text(pick_first(eval_row, ["source_text", "source", "src"]))
    hypothesis = extract_hypothesis(row, stage)

    if not source_text:
        return None, "missing_source_text"
    if not hypothesis:
        return None, "missing_hypothesis_translation"

    return (
        {
            "sample_id": sample_id,
            "split": split,
            "system_or_group": clean_text(
                pick_first(row, ["system_or_group", "experiment_group", "group"])
            )
            or group,
            "translation_stage": stage,
            "source_text": source_text,
            "hypothesis_translation": hypothesis,
            "source_lang": clean_text(pick_first(row, ["source_lang"]) or eval_row.get("source_lang")),
            "target_lang": clean_text(pick_first(row, ["target_lang"]) or eval_row.get("target_lang")),
            "language_pair": clean_text(pick_first(row, ["language_pair"]) or eval_row.get("language_pair")),
            "document_id": clean_text(pick_first(row, ["document_id"]) or eval_row.get("document_id")),
            "input_source": input_source,
            "translation_source": clean_text(row.get("_xcomet_translation_source")) or stage,
        },
        None,
    )


def merged_da_meta(row: dict[str, Any], sample_id: str, da_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if sample_id in da_index:
        meta.update(da_index[sample_id])
        for name in DA_FIELD_NAMES:
            value = row.get(name)
            current = meta.get(name)
            if (current is None or current == "") and value is not None and value != "":
                meta[name] = value
    else:
        copy_da_fields(meta, row)
    return meta


def da_filter_reason(meta: dict[str, Any], min_confidence: float) -> str | None:
    use_for_da = truthy(meta.get("use_for_da"))
    if use_for_da is not True:
        return "use_for_da_not_true"

    if not clean_text(meta.get("ref_text")):
        return "missing_ref_text"

    score = confidence_score(meta.get("alignment_confidence"))
    if score is None:
        return "missing_alignment_confidence"
    if score < min_confidence:
        return "alignment_confidence_below_threshold"

    if is_explicitly_unaligned(meta):
        return "source_ref_not_aligned"
    if is_summary_ref(meta):
        return "summary_ref"
    if is_unconfirmed_machine_ref(meta):
        return "machine_ref_unconfirmed"
    return None


def build_da_record(
    common: dict[str, Any],
    row: dict[str, Any],
    da_index: dict[str, dict[str, Any]],
    *,
    min_confidence: float,
) -> tuple[dict[str, Any] | None, str | None]:
    meta = merged_da_meta(row, common["sample_id"], da_index)
    reason = da_filter_reason(meta, min_confidence)
    if reason:
        return None, reason

    ref_source = clean_text(pick_first(meta, ["ref_source", "reference_source"]))
    if not ref_source:
        ref_source = clean_text(meta.get("_da_source_path")) or (
            f"data/eval/splits/{REFERENCE_WITH_REF_SPLIT}/all_samples_with_reference.jsonl"
        )

    record = dict(common)
    record.update(
        {
            "ref_text": clean_text(meta.get("ref_text")),
            "use_for_da": True,
            "alignment_confidence": meta.get("alignment_confidence"),
            "alignment_confidence_score": confidence_score(meta.get("alignment_confidence")),
            "alignment_method": clean_text(meta.get("alignment_method")),
            "ref_source": ref_source,
            "da_filter_reason": None,
        }
    )
    for name in ["page_ref", "order_ref"]:
        if meta.get(name) is not None:
            record[name] = meta[name]
    return record, None


def rel_output(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    args = parse_args()
    stages = [normalize_stage(stage) for stage in args.stages]
    output_dir = resolve_path(args.output_dir)
    errors: list[str] = []

    da_outputs: dict[str, list[dict[str, Any]]] = {split: [] for split in args.splits}
    stats: dict[str, Any] = {
        "params": {
            "splits": args.splits,
            "groups": args.groups,
            "stages": stages,
            "reference_split": args.reference_split,
            "min_alignment_confidence": args.min_alignment_confidence,
            "output_dir": args.output_dir,
            "dry_run": args.dry_run,
            "strict": args.strict,
        },
        "splits": {},
    }

    for split in args.splits:
        all_index, da_index, data_sources = load_eval_indexes(split, reference_split=args.reference_split)
        split_stats: dict[str, Any] = {
            "data_sources": data_sources,
            "source_samples": len(all_index),
            "reference_samples": len(da_index),
            "da_records": 0,
            "groups": {},
        }

        for stage in stages:
            for group in args.groups:
                rows, input_source = load_stage_rows(split, group, stage, errors, strict=args.strict)
                key = f"{stage}/{group}"
                group_stats: dict[str, Any] = {
                    "input_source": input_source,
                    "input_rows": len(rows),
                    "da_records": 0,
                    "skipped_required": {},
                    "da_filtered": {},
                }
                required_skips: Counter[str] = Counter()
                da_filtered: Counter[str] = Counter()

                for row in rows:
                    common, reason = build_common_record(
                        row,
                        split=split,
                        group=group,
                        stage=stage,
                        all_index=all_index,
                        input_source=input_source,
                    )
                    if reason:
                        required_skips[reason] += 1
                        continue

                    da_record, da_reason = build_da_record(
                        common,
                        row,
                        da_index,
                        min_confidence=args.min_alignment_confidence,
                    )
                    if da_record is None:
                        if da_reason:
                            da_filtered[da_reason] += 1
                    else:
                        da_outputs[split].append(da_record)
                        group_stats["da_records"] += 1

                group_stats["skipped_required"] = dict(sorted(required_skips.items()))
                group_stats["da_filtered"] = dict(sorted(da_filtered.items()))
                split_stats["da_records"] += group_stats["da_records"]
                split_stats["groups"][key] = group_stats

                if args.strict and required_skips:
                    errors.append(f"{split} {key} has required-field skips: {dict(required_skips)}")

        stats["splits"][split] = split_stats

    stats["outputs"] = {
        split: {
            "da": rel_output(output_dir / f"da_{split}.jsonl"),
            "da_records": len(da_outputs[split]),
        }
        for split in args.splits
    }

    if errors:
        print(json.dumps(stats, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit("Strict validation failed:\n" + "\n".join(f"- {error}" for error in errors))

    if args.dry_run:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    for split in args.splits:
        write_jsonl(output_dir / f"da_{split}.jsonl", da_outputs[split])

    summary_path = ensure_parent(output_dir / "build_xcomet_inputs_summary.json")
    summary_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats["outputs"], ensure_ascii=False, indent=2))
    print(f"Wrote build summary: {rel_output(summary_path)}")


if __name__ == "__main__":
    main()
