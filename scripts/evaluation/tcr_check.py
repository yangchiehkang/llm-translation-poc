#!/usr/bin/env python3
"""Compute hard-term TCR for first translations and prepare TCR retry inputs."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.io_utils import read_csv, read_jsonl, resolve_path, write_jsonl
from scripts.common.lang import normalize_lang
from scripts.common.termbase import split_aliases
from scripts.common.text_utils import utc_now as _utc_now

GROUPS = ["no_term_baseline", "term_baseline", "graded_prompt"]
SPLITS = ["source_only_300_by_lang"]
INPUT_SUFFIX = "_first_translations.jsonl"
OUTPUT_SUFFIX = "_tcr.jsonl"
RETRY_TRANSLATION_SUFFIX = "_retry_translations.jsonl"
RETRY_TCR_SUFFIX = "_retry_tcr.jsonl"
TCR_STATUSES = {"pass", "fail", "no_terms"}
DA_PASSTHROUGH_FIELDS = [
    "ref_text",
    "page_ref",
    "order_ref",
    "alignment_method",
    "alignment_confidence",
    "use_for_da",
]
CORE_OUTPUT_FIELDS = [
    "sample_id",
    "document_id",
    "language_pair",
    "source_lang",
    "target_lang",
    "source_text",
    "hypothesis",
    "experiment_group",
    "prompt_mode",
    "translation_stage",
    "model_name",
    "model_backend",
]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def _norm_code(value: Any) -> str:
    return normalize_lang(str(value or ""))


def _norm_status(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_high_active(term: dict[str, Any]) -> bool:
    return _norm_status(term.get("priority")) == "high" and _norm_status(term.get("status")) == "active"


def _has_ascii(text: str) -> bool:
    return any(ord(ch) < 128 and ch.isalnum() for ch in text)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _collapse_space(text: str) -> str:
    return re.sub(r"\s+", " ", _clean_text(text))


def _compact_space(text: str) -> str:
    return re.sub(r"\s+", "", _clean_text(text))


def _contains_term(text: str, term: str, *, case_insensitive: bool | None = None) -> bool:
    text = _clean_text(text)
    term = _clean_text(term)
    if not text or not term:
        return False
    if case_insensitive is None:
        case_insensitive = _has_ascii(term)
    if _has_ascii(term):
        hay = _collapse_space(text).casefold() if case_insensitive else _collapse_space(text)
        needle = _collapse_space(term).casefold() if case_insensitive else _collapse_space(term)
        if needle in hay:
            return True
        compact_hay = _compact_space(text).casefold() if case_insensitive else _compact_space(text)
        compact_needle = _compact_space(term).casefold() if case_insensitive else _compact_space(term)
        return bool(compact_needle and compact_needle in compact_hay)
    return term in text


def _first_present(text: str, candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate and _contains_term(text, candidate):
            return candidate
    return ""


def _target_present(hypothesis: str, target_term: str) -> bool:
    return _contains_term(hypothesis, target_term)


def _parse_aliases(term: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    raw_aliases = term.get("aliases")
    if isinstance(raw_aliases, list):
        aliases.extend(str(x).strip() for x in raw_aliases if str(x).strip())
    elif raw_aliases:
        aliases.extend(split_aliases(str(raw_aliases)))
    aliases.extend(split_aliases(str(term.get("alias") or "")))

    source_term = _clean_text(term.get("source_term"))
    target_term = _clean_text(term.get("target_term"))
    out: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        alias = _clean_text(alias)
        if not alias or alias == target_term:
            continue
        key = alias.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(alias)
    # A preserved source abbreviation behaves like alias-only, not a hard pass.
    if source_term and source_term != target_term and len(source_term) <= 20:
        key = source_term.casefold()
        if key not in seen:
            out.append(source_term)
    return out


def _partial_observed(hypothesis: str, target_term: str) -> str:
    target_term = _clean_text(target_term)
    hypothesis = _clean_text(hypothesis)
    if not target_term or not hypothesis:
        return ""
    if _has_cjk(target_term):
        cjk_chars = "".join(ch for ch in target_term if "\u4e00" <= ch <= "\u9fff")
        if len(cjk_chars) >= 4:
            spans = sorted(
                {cjk_chars[i:j] for i in range(len(cjk_chars)) for j in range(i + 2, len(cjk_chars) + 1)},
                key=len,
                reverse=True,
            )
            for span in spans:
                if len(span) >= max(2, len(cjk_chars) // 3) and span in hypothesis:
                    return span
    tokens = [tok for tok in re.split(r"[\s\-/()（）,，;；:：]+", target_term) if len(tok) >= 2]
    for token in sorted(tokens, key=len, reverse=True):
        if _contains_term(hypothesis, token):
            return token
    return ""


def _classify_failure(hypothesis: str, term: dict[str, Any]) -> tuple[str, str]:
    hypothesis = _clean_text(hypothesis)
    target_term = _clean_text(term.get("target_term"))
    aliases = _parse_aliases(term)
    alias_hit = _first_present(hypothesis, aliases)
    if alias_hit:
        return "alias_only", alias_hit

    partial = _partial_observed(hypothesis, target_term)
    if partial:
        return "partial", partial

    source_candidates = [
        _clean_text(term.get("matched_text")),
        _clean_text(term.get("source_term")),
    ]
    source_hit = _first_present(hypothesis, [x for x in source_candidates if x])
    if source_hit:
        return "wrong_translation", source_hit

    return "missing", ""


def _dedupe_terms(terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for term in terms:
        target = _clean_text(term.get("target_term"))
        source = _clean_text(term.get("source_term"))
        if not target:
            continue
        # required_target_terms is the preferred contract, so duplicate source rows
        # that require the same target form are one hard requirement for TCR.
        key = (target.casefold(), _norm_code(term.get("target_lang")))
        if key in seen:
            continue
        seen.add(key)
        normalized = dict(term)
        normalized["source_term"] = source
        normalized["target_term"] = target
        normalized["priority"] = _norm_status(term.get("priority"))
        normalized["status"] = _norm_status(term.get("status") or "active")
        normalized["source_lang"] = _norm_code(term.get("source_lang"))
        normalized["target_lang"] = _norm_code(term.get("target_lang") or "zh")
        normalized["aliases"] = _parse_aliases(normalized)
        out.append(normalized)
    return out


def _read_term_value(value: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(value, dict):
        target = (
            value.get("target_term")
            or value.get("required_target_term")
            or value.get("target")
            or value.get("term")
            or ""
        )
        return _clean_text(target), dict(value)
    return _clean_text(value), {}


class TermbaseIndex:
    def __init__(self, path: str | Path) -> None:
        self.path = str(resolve_path(path))
        self.rows: list[dict[str, Any]] = []
        self.by_lang: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.by_target_lang: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self._load(path)

    def _load(self, path: str | Path) -> None:
        for row in read_csv(path):
            term = dict(row)
            term["source_lang"] = _norm_code(row.get("source_lang") or row.get("src_lang"))
            term["target_lang"] = _norm_code(row.get("target_lang") or row.get("tgt_lang") or "zh")
            term["source_term"] = _clean_text(row.get("source_term"))
            term["target_term"] = _clean_text(row.get("target_term"))
            term["priority"] = _norm_status(row.get("priority"))
            term["status"] = _norm_status(row.get("status") or "active")
            term["aliases"] = split_aliases(row.get("alias") or row.get("aliases"))
            if not term["source_term"] or not term["target_term"]:
                continue
            self.rows.append(term)
            self.by_lang.setdefault((term["source_lang"], term["target_lang"]), []).append(term)
            target_key = (term["source_lang"], term["target_lang"], term["target_term"].casefold())
            self.by_target_lang.setdefault(target_key, []).append(term)

        for key, rows in self.by_lang.items():
            rows.sort(key=lambda x: len(str(x.get("source_term") or "")), reverse=True)

    def hard_active_rows(self, source_lang: str, target_lang: str) -> list[dict[str, Any]]:
        return [term for term in self.by_lang.get((source_lang, target_lang), []) if _is_high_active(term)]

    def recall_hard_terms(self, source_text: str, source_lang: str, target_lang: str) -> list[dict[str, Any]]:
        matched: list[dict[str, Any]] = []
        for term in self.hard_active_rows(source_lang, target_lang):
            source_term = _clean_text(term.get("source_term"))
            aliases = [x for x in split_aliases(term.get("alias") or "") if x]
            matched_text = ""
            matched_by = ""
            if _contains_term(source_text, source_term):
                matched_text = source_term
                matched_by = "source_term"
            else:
                for alias in aliases:
                    if _contains_term(source_text, alias):
                        matched_text = alias
                        matched_by = "alias"
                        break
            if not matched_text:
                continue
            out = dict(term)
            out["matched_text"] = matched_text
            out["matched_by"] = matched_by
            matched.append(out)
        return _dedupe_terms(matched)

    def target_lookup(self, target: str, source_lang: str, target_lang: str) -> list[dict[str, Any]]:
        key = (source_lang, target_lang, _clean_text(target).casefold())
        return [term for term in self.by_target_lang.get(key, []) if _is_high_active(term)]


def _row_langs(row: dict[str, Any]) -> tuple[str, str]:
    source_lang = _norm_code(row.get("source_lang"))
    target_lang = _norm_code(row.get("target_lang") or "zh")
    if not source_lang:
        pair = str(row.get("language_pair") or "")
        if "-" in pair:
            source_lang = _norm_code(pair.split("-", 1)[0])
    return source_lang, target_lang or "zh"


def _hard_terms_from_matched(row: dict[str, Any]) -> list[dict[str, Any]]:
    matched = row.get("matched_terms") or []
    if isinstance(matched, str):
        try:
            matched = json.loads(matched)
        except json.JSONDecodeError:
            matched = []
    if not isinstance(matched, list):
        return []
    return _dedupe_terms([term for term in matched if isinstance(term, dict) and _is_high_active(term)])


def _required_hard_terms(row: dict[str, Any], index: TermbaseIndex) -> list[dict[str, Any]]:
    source_lang, target_lang = _row_langs(row)
    source_text = _clean_text(row.get("source_text"))
    matched_hard = _hard_terms_from_matched(row)
    matched_by_target: dict[str, list[dict[str, Any]]] = {}
    for term in matched_hard:
        matched_by_target.setdefault(_clean_text(term.get("target_term")).casefold(), []).append(term)

    required_raw = row.get("required_target_terms") or []
    if isinstance(required_raw, str):
        try:
            required_raw = json.loads(required_raw)
        except json.JSONDecodeError:
            required_raw = [required_raw]
    required: list[dict[str, Any]] = []
    if isinstance(required_raw, list):
        for item in required_raw:
            target, metadata = _read_term_value(item)
            if not target:
                continue
            if metadata and _is_high_active(metadata):
                required.append(metadata)
                continue
            candidates = matched_by_target.get(target.casefold()) or []
            if candidates:
                required.append(candidates[0])
                continue
            for candidate in index.target_lookup(target, source_lang, target_lang):
                if _contains_term(source_text, candidate.get("source_term", "")) or _first_present(
                    source_text, split_aliases(candidate.get("alias") or "")
                ):
                    required.append(candidate)
                    break

    if required:
        return _dedupe_terms(required)
    if matched_hard:
        return matched_hard
    return index.recall_hard_terms(source_text, source_lang, target_lang)


def _sample_error_type(failed_terms: list[dict[str, Any]]) -> str:
    if not failed_terms:
        return "none"
    types = {str(term.get("error_type") or "missing") for term in failed_terms}
    return next(iter(types)) if len(types) == 1 else "mixed"


def _ordered_tcr_row(row: dict[str, Any], tcr_fields: dict[str, Any], hard_terms: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in CORE_OUTPUT_FIELDS:
        out[field] = row.get(field, "")
    for field in DA_PASSTHROUGH_FIELDS:
        if field in row:
            out[field] = row.get(field)
    out["required_target_terms"] = [term.get("target_term", "") for term in hard_terms]
    out["hard_required_terms"] = hard_terms
    out.update(tcr_fields)
    return out


def evaluate_row(row: dict[str, Any], index: TermbaseIndex) -> dict[str, Any]:
    hard_terms = _required_hard_terms(row, index)
    hypothesis = _clean_text(row.get("hypothesis") or row.get("translation") or row.get("translated_text"))
    failed_terms: list[dict[str, Any]] = []
    correct_count = 0

    for term in hard_terms:
        required_target = _clean_text(term.get("target_term"))
        if _target_present(hypothesis, required_target):
            correct_count += 1
            continue
        error_type, observed = _classify_failure(hypothesis, term)
        failed_terms.append({
            "term_id": term.get("term_id", ""),
            "source_term": term.get("source_term", ""),
            "required_target_term": required_target,
            "observed": observed,
            "error_type": error_type,
        })

    matched_count = len(hard_terms)
    if matched_count == 0:
        tcr_sample = None
        tcr_status = "no_terms"
    else:
        tcr_sample = round(correct_count / matched_count * 100, 4)
        tcr_status = "pass" if correct_count == matched_count else "fail"

    tcr_fields = {
        "matched_hard_term_count": matched_count,
        "correct_hard_term_count": correct_count,
        "failed_terms": failed_terms,
        "tcr_sample": tcr_sample,
        "tcr_status": tcr_status,
        "error_type": _sample_error_type(failed_terms),
    }
    return _ordered_tcr_row(row, tcr_fields, hard_terms)


def _retry_prompt(row: dict[str, Any]) -> str:
    failed_lines = []
    for term in row.get("failed_terms") or []:
        failed_lines.append(
            f"- {term.get('source_term', '')} -> {term.get('required_target_term', '')} "
            f"(error_type={term.get('error_type', '')})"
        )
    failed_text = "\n".join(failed_lines) if failed_lines else "- 无"
    return (
        "请只修正以下法规/标准译文。\n"
        "要求：\n"
        "1. 只修正译文，不改写源文含义。\n"
        "2. 必须保留法律/法规文本风格。\n"
        "3. 必须使用 failed_terms 中列出的指定译法。\n"
        "4. 不要输出解释。\n"
        "5. 不要输出术语列表。\n"
        "6. 只输出修正后的完整译文。\n\n"
        f"源文：\n{row.get('source_text', '')}\n\n"
        f"上一版译文：\n{row.get('hypothesis', '')}\n\n"
        f"failed_terms：\n{failed_text}\n\n"
        "修正后的完整译文："
    )


def build_retry_rows(tcr_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    retry_rows = []
    for row in tcr_rows:
        if row.get("tcr_status") != "fail":
            continue
        retry_row = {
            "sample_id": row.get("sample_id"),
            "document_id": row.get("document_id"),
            "language_pair": row.get("language_pair"),
            "source_lang": row.get("source_lang"),
            "target_lang": row.get("target_lang"),
            "source_text": row.get("source_text"),
            "previous_hypothesis": row.get("hypothesis"),
            "experiment_group": row.get("experiment_group"),
            "prompt_mode": row.get("prompt_mode"),
            "failed_terms": row.get("failed_terms") or [],
            "required_target_terms": row.get("required_target_terms") or [],
            "retry_prompt_text": _retry_prompt(row),
            "retry_reason": "tcr_fail",
            "translation_stage": "retry_tcr",
            "da_delta_after_retry": "not_run",
        }
        for field in DA_PASSTHROUGH_FIELDS:
            if field in row:
                retry_row[field] = row.get(field)
        retry_rows.append(retry_row)
    return retry_rows


def _summarize_group(group: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    hard_rows = [row for row in rows if row["matched_hard_term_count"] > 0]
    pass_count = sum(1 for row in rows if row["tcr_status"] == "pass")
    fail_count = sum(1 for row in rows if row["tcr_status"] == "fail")
    no_terms_count = sum(1 for row in rows if row["tcr_status"] == "no_terms")
    avg_tcr = (
        round(sum(float(row["tcr_sample"]) for row in hard_rows if row["tcr_sample"] is not None) / len(hard_rows), 4)
        if hard_rows
        else None
    )
    pass_rate = round(pass_count / len(hard_rows) * 100, 4) if hard_rows else None
    retry_needed = fail_count
    failed_term_counter: Counter[str] = Counter()
    error_counter: Counter[str] = Counter()
    sample_error_counter: Counter[str] = Counter(row["error_type"] for row in rows)
    for row in rows:
        for failed in row.get("failed_terms") or []:
            source = failed.get("source_term") or ""
            target = failed.get("required_target_term") or ""
            key = f"{source} -> {target}".strip()
            failed_term_counter[key] += 1
            error_counter[str(failed.get("error_type") or "missing")] += 1
    return {
        "experiment_group": group,
        "total_samples": len(rows),
        "samples_with_hard_terms": len(hard_rows),
        "no_terms_count": no_terms_count,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate_on_hard_terms": pass_rate,
        "avg_tcr_on_hard_terms": avg_tcr,
        "failed_term_total": sum(failed_term_counter.values()),
        "top_failed_terms": [{"term": term, "count": count} for term, count in failed_term_counter.most_common(10)],
        "error_type_distribution": dict(sorted(error_counter.items())),
        "sample_error_type_distribution": dict(sorted(sample_error_counter.items())),
        "retry_needed_count": retry_needed,
        "retry_rate": round(retry_needed / len(rows) * 100, 4) if rows else None,
        "retry_success_count": "not_run",
        "retry_fix_rate": "not_run",
        "tcr_before_retry": avg_tcr,
        "tcr_after_retry": "not_run",
        "da_delta_after_retry": "not_run",
    }


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, str):
        return value
    return f"{float(value):.2f}%"


def _fmt_num(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _pct(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _dir_for_split(base_dir: str | Path, split_name: str) -> Path:
    base = resolve_path(base_dir)
    return base if base.name == split_name else base / split_name


def write_summary(
    split_name: str,
    output_dir: Path,
    retry_output_dir: Path,
    summaries: dict[str, dict[str, Any]],
) -> None:
    lines = [
        f"# TCR Summary - {split_name}",
        "",
        "## Group Comparison",
        "| group | total_samples | samples_with_hard_terms | no_terms_count | pass_count | fail_count | pass_rate_on_hard_terms | avg_tcr_on_hard_terms | failed_term_total | retry_needed_count | retry_rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for group in GROUPS:
        summary = summaries[group]
        lines.append(
            "| {group} | {total} | {hard} | {no_terms} | {passed} | {failed} | {pass_rate} | {avg_tcr} | {failed_terms} | {retry_needed} | {retry_rate} |".format(
                group=group,
                total=summary["total_samples"],
                hard=summary["samples_with_hard_terms"],
                no_terms=summary["no_terms_count"],
                passed=summary["pass_count"],
                failed=summary["fail_count"],
                pass_rate=_fmt_pct(summary["pass_rate_on_hard_terms"]),
                avg_tcr=_fmt_num(summary["avg_tcr_on_hard_terms"]),
                failed_terms=summary["failed_term_total"],
                retry_needed=summary["retry_needed_count"],
                retry_rate=_fmt_pct(summary["retry_rate"]),
            )
        )

    lines.extend([
        "",
        "## Error Type Distribution",
        "| group | error_type_distribution | sample_error_type_distribution |",
        "|---|---|---|",
    ])
    for group in GROUPS:
        summary = summaries[group]
        lines.append(
            f"| {group} | `{json.dumps(summary['error_type_distribution'], ensure_ascii=False)}` | "
            f"`{json.dumps(summary['sample_error_type_distribution'], ensure_ascii=False)}` |"
        )

    lines.extend([
        "",
        "## Top Failed Terms",
    ])
    for group in GROUPS:
        top = summaries[group]["top_failed_terms"]
        lines.append(f"### {group}")
        if not top:
            lines.append("- 无")
        else:
            for item in top:
                lines.append(f"- {item['term']}: {item['count']}")

    lines.extend([
        "",
        "## Retry Planning",
        "| group | retry_input | retry_needed_count | retry_rate | retry_success_count | retry_fix_rate | tcr_before_retry | tcr_after_retry | da_delta_after_retry |",
        "|---|---|---:|---:|---|---|---:|---|---|",
    ])
    for group in GROUPS:
        summary = summaries[group]
        retry_input = retry_output_dir / f"{group}_retry_inputs.jsonl"
        lines.append(
            f"| {group} | `{retry_input}` | {summary['retry_needed_count']} | {_fmt_pct(summary['retry_rate'])} | "
            f"{summary['retry_success_count']} | {summary['retry_fix_rate']} | {_fmt_num(summary['tcr_before_retry'])} | "
            f"{summary['tcr_after_retry']} | {summary['da_delta_after_retry']} |"
        )

    lines.extend([
        "",
        "## Checks",
        "- TCR 只检查 priority=high 且 status=active 的 hard required terms。",
        "- tcr_status 只使用 pass / fail / no_terms。",
        "- no_terms 样本的 tcr_sample 为 null；pass/fail 样本为 0 到 100。",
        "- retry_inputs 只包含 tcr_status=fail 的样本。",
        "- 当前未执行 retry 翻译、DA/COMET，也未调用 API。",
    ])
    (output_dir / "tcr_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    machine_summary = {
        "split_name": split_name,
        "groups": summaries,
        "output_dir": str(output_dir),
        "retry_output_dir": str(retry_output_dir),
        "retry_translation_executed": False,
        "da_executed": False,
        "xcomet_executed": False,
        "api_called": False,
    }
    (output_dir / "tcr_summary.json").write_text(json.dumps(machine_summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _first_tcr_index(path: Path) -> dict[str, dict[str, Any]]:
    rows = read_jsonl(path)
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        sample_id = str(row.get("sample_id") or "")
        if not sample_id:
            continue
        if sample_id in indexed:
            raise ValueError(f"Duplicate sample_id in first-pass TCR file {path}: {sample_id}")
        indexed[sample_id] = row
    return indexed


def _retry_eval_row(retry_row: dict[str, Any], first_row: dict[str, Any]) -> dict[str, Any]:
    row = dict(first_row)
    row.update(retry_row)
    row["hypothesis"] = retry_row.get("retry_translation") or ""
    row["source_text"] = retry_row.get("source_text") or first_row.get("source_text") or ""
    row["source_lang"] = retry_row.get("source_lang") or first_row.get("source_lang") or ""
    row["target_lang"] = retry_row.get("target_lang") or first_row.get("target_lang") or "zh"
    row["language_pair"] = retry_row.get("language_pair") or first_row.get("language_pair") or ""
    row["matched_terms"] = first_row.get("hard_required_terms") or first_row.get("matched_terms") or []
    row["required_target_terms"] = first_row.get("required_target_terms") or retry_row.get("required_target_terms") or []
    return row


def _build_retry_tcr_output_row(
    *,
    retry_row: dict[str, Any],
    first_row: dict[str, Any],
    after_row: dict[str, Any],
    split_name: str,
    group: str,
    created_at: str,
) -> dict[str, Any]:
    before_status = first_row.get("tcr_status") or retry_row.get("tcr_status_before_retry")
    before_sample = first_row.get("tcr_sample")
    if before_sample is None and "tcr_sample_before_retry" in retry_row:
        before_sample = retry_row.get("tcr_sample_before_retry")
    after_status = after_row["tcr_status"]
    before_missing = first_row.get("failed_terms") or retry_row.get("missing_hard_terms") or []
    after_missing = after_row.get("failed_terms") or []
    total_hard_terms = int(after_row.get("matched_hard_term_count") or 0)

    return {
        "sample_id": retry_row.get("sample_id") or first_row.get("sample_id"),
        "split": retry_row.get("split") or split_name,
        "group": retry_row.get("group") or retry_row.get("experiment_group") or group,
        "source_text": retry_row.get("source_text") or first_row.get("source_text") or "",
        "original_translation": retry_row.get("original_translation") or first_row.get("hypothesis") or "",
        "retry_translation": retry_row.get("retry_translation") or "",
        "required_target_terms": after_row.get("required_target_terms") or [],
        "missing_hard_terms": before_missing,
        "tcr_status_before_retry": before_status,
        "tcr_sample_before_retry": before_sample,
        "tcr_status_after_retry": after_status,
        "tcr_sample_after_retry": after_row.get("tcr_sample"),
        "matched_hard_term_count_after_retry": total_hard_terms,
        "correct_hard_term_count_after_retry": after_row.get("correct_hard_term_count"),
        "total_hard_term_count": total_hard_terms,
        "missing_hard_terms_after_retry": after_missing,
        "recovered": before_status == "fail" and after_status == "pass",
        "still_fail": before_status == "fail" and after_status == "fail",
        "model_path": retry_row.get("model_path") or "",
        "retry_attempt": retry_row.get("retry_attempt"),
        "created_at": created_at,
        "first_pass_tcr_file_status": first_row.get("tcr_status"),
        "retry_translation_status": retry_row.get("status"),
        "hard_required_terms_after_retry": after_row.get("hard_required_terms") or [],
        "error_type_after_retry": after_row.get("error_type"),
    }


def _summarize_retry_group(
    split_name: str,
    group: str,
    first_rows: list[dict[str, Any]],
    retry_tcr_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    hard_rows = [row for row in first_rows if int(row.get("matched_hard_term_count") or 0) > 0]
    first_pass_pass_count = sum(1 for row in first_rows if row.get("tcr_status") == "pass")
    first_pass_fail_count = sum(1 for row in first_rows if row.get("tcr_status") == "fail")
    recovered_count = sum(1 for row in retry_tcr_rows if row.get("recovered") is True)
    still_fail_count = sum(1 for row in retry_tcr_rows if row.get("still_fail") is True)

    paired_gains: list[float] = []
    before_values: list[float] = []
    after_values: list[float] = []
    for row in retry_tcr_rows:
        before = _to_float(row.get("tcr_sample_before_retry"))
        after = _to_float(row.get("tcr_sample_after_retry"))
        if before is not None:
            before_values.append(before)
        if after is not None:
            after_values.append(after)
        if before is not None and after is not None:
            paired_gains.append(after - before)

    final_pass_count = first_pass_pass_count + recovered_count
    final_fail_count = still_fail_count
    samples_with_hard_terms = len(hard_rows)
    return {
        "split": split_name,
        "group": group,
        "retry_input_count": len(retry_tcr_rows),
        "recovered_count": recovered_count,
        "still_fail_count": still_fail_count,
        "retry_recovery_rate": _pct(recovered_count, len(retry_tcr_rows)),
        "avg_tcr_before_retry": _mean(before_values),
        "avg_tcr_after_retry": _mean(after_values),
        "avg_tcr_gain": _mean(paired_gains),
        "first_pass_pass_count": first_pass_pass_count,
        "first_pass_fail_count": first_pass_fail_count,
        "samples_with_hard_terms": samples_with_hard_terms,
        "final_pass_count": final_pass_count,
        "final_fail_count": final_fail_count,
        "final_pass_rate_on_hard_terms": _pct(final_pass_count, samples_with_hard_terms),
        "_avg_before_count": len(before_values),
        "_avg_after_count": len(after_values),
        "_avg_gain_count": len(paired_gains),
    }


def _retry_summary_table_lines(summaries: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| split | group | retry_input_count | recovered_count | still_fail_count | retry_recovery_rate | avg_tcr_before_retry | avg_tcr_after_retry | avg_tcr_gain | first_pass_pass_count | first_pass_fail_count | samples_with_hard_terms | final_pass_count | final_fail_count | final_pass_rate_on_hard_terms |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        lines.append(
            "| {split} | {group} | {retry_input_count} | {recovered_count} | {still_fail_count} | {retry_recovery_rate} | {avg_before} | {avg_after} | {avg_gain} | {first_pass_pass_count} | {first_pass_fail_count} | {samples_with_hard_terms} | {final_pass_count} | {final_fail_count} | {final_pass_rate} |".format(
                split=summary["split"],
                group=summary["group"],
                retry_input_count=summary["retry_input_count"],
                recovered_count=summary["recovered_count"],
                still_fail_count=summary["still_fail_count"],
                retry_recovery_rate=_fmt_pct(summary["retry_recovery_rate"]),
                avg_before=_fmt_num(summary["avg_tcr_before_retry"]),
                avg_after=_fmt_num(summary["avg_tcr_after_retry"]),
                avg_gain=_fmt_num(summary["avg_tcr_gain"]),
                first_pass_pass_count=summary["first_pass_pass_count"],
                first_pass_fail_count=summary["first_pass_fail_count"],
                samples_with_hard_terms=summary["samples_with_hard_terms"],
                final_pass_count=summary["final_pass_count"],
                final_fail_count=summary["final_fail_count"],
                final_pass_rate=_fmt_pct(summary["final_pass_rate_on_hard_terms"]),
            )
        )
    return lines


def write_retry_summary(
    split_name: str,
    output_dir: Path,
    retry_translation_dir: Path,
    first_tcr_dir: Path,
    summaries: dict[str, dict[str, Any]],
    generated_files: dict[str, dict[str, str]],
) -> None:
    lines = [
        f"# TCR Retry Recheck Summary - {split_name}",
        "",
        "## Recovery Summary",
        *_retry_summary_table_lines([summaries[group] for group in GROUPS]),
        "",
        "## Files",
        "| group | retry_translation_input | first_pass_tcr_input | retry_tcr_output |",
        "|---|---|---|---|",
    ]
    for group in GROUPS:
        files = generated_files[group]
        lines.append(
            f"| {group} | `{files['retry_translation_input']}` | `{files['first_pass_tcr_input']}` | `{files['retry_tcr_output']}` |"
        )

    lines.extend([
        "",
        "## Checks",
        "- TCR 口径复用 Step 6 hard-term TCR 逻辑。",
        "- 只检查 priority=high 且 status=active 的 hard required terms。",
        "- tcr_status_after_retry 只使用 pass / fail / no_terms。",
        "- no_terms 样本的 tcr_sample_after_retry 为 null；pass/fail 样本为 0 到 100。",
        "- recovered = tcr_status_before_retry == fail 且 tcr_status_after_retry == pass。",
        "- still_fail = tcr_status_before_retry == fail 且 tcr_status_after_retry == fail。",
        "- first-pass 指标读取自 Step 6 TCR JSONL，不手工硬编码。",
        "- 本步骤未执行 retry 翻译、DA/COMET，也未调用外部 API。",
        "",
        f"Retry translation dir: `{retry_translation_dir}`",
        f"First-pass TCR dir: `{first_tcr_dir}`",
    ])
    (output_dir / "tcr_retry_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _aggregate_retry_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    retry_input_count = sum(int(s["retry_input_count"]) for s in summaries)
    recovered_count = sum(int(s["recovered_count"]) for s in summaries)
    still_fail_count = sum(int(s["still_fail_count"]) for s in summaries)
    first_pass_pass_count = sum(int(s["first_pass_pass_count"]) for s in summaries)
    first_pass_fail_count = sum(int(s["first_pass_fail_count"]) for s in summaries)
    samples_with_hard_terms = sum(int(s["samples_with_hard_terms"]) for s in summaries)
    final_pass_count = first_pass_pass_count + recovered_count
    final_fail_count = still_fail_count

    def weighted_avg(key: str, count_key: str) -> float | None:
        total = 0.0
        count = 0
        for summary in summaries:
            value = _to_float(summary.get(key))
            value_count = int(summary.get(count_key) or 0)
            if value is None or value_count == 0:
                continue
            total += value * value_count
            count += value_count
        return round(total / count, 4) if count else None

    return {
        "split": "all",
        "group": "all",
        "retry_input_count": retry_input_count,
        "recovered_count": recovered_count,
        "still_fail_count": still_fail_count,
        "retry_recovery_rate": _pct(recovered_count, retry_input_count),
        "avg_tcr_before_retry": weighted_avg("avg_tcr_before_retry", "_avg_before_count"),
        "avg_tcr_after_retry": weighted_avg("avg_tcr_after_retry", "_avg_after_count"),
        "avg_tcr_gain": weighted_avg("avg_tcr_gain", "_avg_gain_count"),
        "first_pass_pass_count": first_pass_pass_count,
        "first_pass_fail_count": first_pass_fail_count,
        "samples_with_hard_terms": samples_with_hard_terms,
        "final_pass_count": final_pass_count,
        "final_fail_count": final_fail_count,
        "final_pass_rate_on_hard_terms": _pct(final_pass_count, samples_with_hard_terms),
    }


def write_retry_summary_all(root_output_dir: Path, summaries_by_split: dict[str, dict[str, dict[str, Any]]]) -> None:
    all_group_summaries = [summaries_by_split[split][group] for split in summaries_by_split for group in GROUPS]
    lines = [
        "# TCR Retry Recheck Summary - All Splits",
        "",
        "## Overall",
        *_retry_summary_table_lines([_aggregate_retry_summaries(all_group_summaries)]),
        "",
        "## Split And Group Details",
        *_retry_summary_table_lines(all_group_summaries),
        "",
        "## Scope",
        "- 本汇总仅覆盖 Step 7 retry translation outputs。",
        "- first-pass 指标读取自 Step 6 TCR JSONL。",
        "- 本步骤未执行 retry 翻译、DA/COMET，也未调用外部 API。",
    ]
    root_output_dir.mkdir(parents=True, exist_ok=True)
    (root_output_dir / "tcr_retry_summary_all.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_retry_recheck(args: argparse.Namespace) -> dict[str, Any]:
    split_names = SPLITS if not args.split_name or args.split_name == "all" else [args.split_name]
    unknown_splits = [split for split in split_names if split not in SPLITS]
    if unknown_splits:
        raise ValueError(f"Unsupported split(s): {unknown_splits}; expected one of {SPLITS} or all")

    base_output_dir = resolve_path(args.output_dir or "outputs/evaluation/tcr_retry")
    root_output_dir = base_output_dir.parent if len(split_names) == 1 and base_output_dir.name in SPLITS else base_output_dir
    retry_translation_base = args.retry_translation_dir or "outputs/translations_retry"
    first_tcr_base = args.first_tcr_dir or "outputs/evaluation/tcr"
    index = TermbaseIndex(args.termbase)
    created_at = _utc_now()

    summaries_by_split: dict[str, dict[str, dict[str, Any]]] = {}
    generated_files: dict[str, dict[str, dict[str, str]]] = {}
    for split_name in split_names:
        split_output_dir = _dir_for_split(base_output_dir, split_name)
        retry_translation_dir = _dir_for_split(retry_translation_base, split_name)
        first_tcr_dir = _dir_for_split(first_tcr_base, split_name)
        split_output_dir.mkdir(parents=True, exist_ok=True)

        split_summaries: dict[str, dict[str, Any]] = {}
        split_files: dict[str, dict[str, str]] = {}
        for group in GROUPS:
            retry_translation_path = retry_translation_dir / f"{group}{RETRY_TRANSLATION_SUFFIX}"
            first_tcr_path = first_tcr_dir / f"{group}{OUTPUT_SUFFIX}"
            retry_tcr_path = split_output_dir / f"{group}{RETRY_TCR_SUFFIX}"
            first_rows = read_jsonl(first_tcr_path)
            first_index = _first_tcr_index(first_tcr_path)
            retry_rows = read_jsonl(retry_translation_path)
            retry_tcr_rows: list[dict[str, Any]] = []
            for retry_row in retry_rows:
                sample_id = str(retry_row.get("sample_id") or "")
                if sample_id not in first_index:
                    raise ValueError(f"{sample_id} from {retry_translation_path} not found in {first_tcr_path}")
                first_row = first_index[sample_id]
                after_row = evaluate_row(_retry_eval_row(retry_row, first_row), index)
                retry_tcr_rows.append(
                    _build_retry_tcr_output_row(
                        retry_row=retry_row,
                        first_row=first_row,
                        after_row=after_row,
                        split_name=split_name,
                        group=group,
                        created_at=created_at,
                    )
                )

            write_jsonl(retry_tcr_path, retry_tcr_rows)
            split_summaries[group] = _summarize_retry_group(split_name, group, first_rows, retry_tcr_rows)
            split_files[group] = {
                "retry_translation_input": str(retry_translation_path),
                "first_pass_tcr_input": str(first_tcr_path),
                "retry_tcr_output": str(retry_tcr_path),
            }

        write_retry_summary(
            split_name,
            split_output_dir,
            retry_translation_dir,
            first_tcr_dir,
            split_summaries,
            split_files,
        )
        summaries_by_split[split_name] = split_summaries
        generated_files[split_name] = split_files

    write_retry_summary_all(root_output_dir, summaries_by_split)
    return {
        "mode": "retry_recheck",
        "created_at": created_at,
        "output_root": str(root_output_dir),
        "generated_files": generated_files,
        "summaries": summaries_by_split,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "mode", "first_pass") == "retry_recheck":
        return run_retry_recheck(args)
    if not args.split_name:
        raise ValueError("--split-name is required in first_pass mode")
    if not args.translation_dir:
        raise ValueError("--translation-dir is required in first_pass mode")
    if not args.output_dir:
        raise ValueError("--output-dir is required in first_pass mode")
    translation_dir = resolve_path(args.translation_dir)
    output_dir = resolve_path(args.output_dir)
    retry_output_dir = resolve_path(args.retry_output_dir or Path("outputs/retry_inputs") / args.split_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    retry_output_dir.mkdir(parents=True, exist_ok=True)
    index = TermbaseIndex(args.termbase)

    summaries: dict[str, dict[str, Any]] = {}
    generated_files: dict[str, dict[str, str]] = {}
    for group in GROUPS:
        input_path = translation_dir / f"{group}{INPUT_SUFFIX}"
        output_path = output_dir / f"{group}{OUTPUT_SUFFIX}"
        retry_path = retry_output_dir / f"{group}_retry_inputs.jsonl"
        rows = read_jsonl(input_path)
        tcr_rows = [evaluate_row(row, index) for row in rows]
        write_jsonl(output_path, tcr_rows)
        retry_rows = build_retry_rows(tcr_rows)
        write_jsonl(retry_path, retry_rows)
        summaries[group] = _summarize_group(group, tcr_rows)
        generated_files[group] = {
            "input": str(input_path),
            "tcr_output": str(output_path),
            "retry_input": str(retry_path),
        }

    write_summary(args.split_name, output_dir, retry_output_dir, summaries)
    return {
        "split_name": args.split_name,
        "output_dir": str(output_dir),
        "retry_output_dir": str(retry_output_dir),
        "generated_files": generated_files,
        "summaries": summaries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute hard-term TCR and TCR retry inputs.")
    parser.add_argument("--mode", choices=["first_pass", "retry_recheck"], default="first_pass")
    parser.add_argument("--split-name", default="")
    parser.add_argument("--translation-dir", default="")
    parser.add_argument("--termbase", default="termbase/auto_regulation_terms_v1.csv")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--retry-output-dir", default="")
    parser.add_argument("--retry-translation-dir", default="")
    parser.add_argument("--first-tcr-dir", default="")
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
