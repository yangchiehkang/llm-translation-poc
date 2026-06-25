"""
TCR V0.3 — Dual-metric Term Consistency Rate checker.

Key changes from V0.2:
1. Uses core_high_terms_v0.3_candidate.csv (filtered high+active+zh terms)
2. Two statistical approaches:
   - strict TCR: exact match on target_term only (external acceptance)
   - relaxed TCR: also accepts alias matches + reasonable variants (internal diagnosis)
3. Separately tracks core high terms (tcr_scope=strict) for external reporting
4. Focuses on RFP languages: en/ru/es/de/fr/th/ar
5. Sample review of error types to distinguish real errors vs statistical false positives
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.utils.lang_map import (
    RFP_LANGUAGES,
    get_lang_name,
    is_rfp_language,
)

# ── Constants ────────────────────────────────────────────────────────────────

LANGS = [
    "ar", "de", "en", "es", "fr",
    "id", "it", "ms", "nl", "no",
    "pt", "ru", "sv", "th", "vi",
]

RFP_LANGS = list(RFP_LANGUAGES.keys())

ERROR_TYPES = [
    "no_error",
    "missing",
    "wrong_translation",
    "partial_match",
    "ambiguous",
]

SOURCE_FIELD_CANDIDATES = [
    "source", "src", "src_text", "source_text",
    "text", "input", "sentence", "segment", "source_sentence",
]

PREDICTION_FIELD_CANDIDATES = [
    "mt_text", "prediction", "pred", "translation",
    "mt", "hypothesis", "output", "target", "target_text", "translated_text",
]

ID_FIELD_CANDIDATES = [
    "id", "seg_id", "sample_id", "sentence_id", "uid",
]

# ── V0.3 term loading (with alias + tcr_scope support) ──────────────────────

V03_TERMBASE_COLUMNS = [
    "term_id", "source_lang", "target_lang", "source_term", "target_term",
    "domain", "priority", "alias", "note", "status", "tcr_scope", "acceptance_scope",
]


def load_terms_v03(
    termbase_path: str,
    source_lang: str = None,
    target_lang: str = "zh",
) -> List[Dict]:
    """Load terms from V0.3 candidate CSV with alias and tcr_scope fields."""
    path = Path(termbase_path)
    if not path.exists():
        raise FileNotFoundError(f"Termbase file not found: {path}")

    terms = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"Empty termbase file: {path}")

        for row in reader:
            term_id = str(row.get("term_id", "")).strip()
            src_lang = str(row.get("source_lang", "")).strip()
            src_term = str(row.get("source_term", "")).strip()
            tgt_lang = str(row.get("target_lang", "")).strip()
            tgt_term = str(row.get("target_term", "")).strip()

            if not term_id or not src_lang or not src_term or not tgt_lang or not tgt_term:
                continue
            if source_lang and src_lang != source_lang:
                continue
            if target_lang and tgt_lang != target_lang:
                continue

            alias_raw = str(row.get("alias", "") or "").strip()
            # alias can be semicolon- or comma-separated list
            aliases: List[str] = []
            if alias_raw:
                # Try semicolon first, then comma
                if ";" in alias_raw:
                    aliases = [a.strip() for a in alias_raw.split(";") if a.strip()]
                elif "," in alias_raw:
                    aliases = [a.strip() for a in alias_raw.split(",") if a.strip()]
                else:
                    aliases = [alias_raw]

            tcr_scope = str(row.get("tcr_scope", "")).strip()

            term = {
                "term_id": term_id,
                "source_lang": src_lang,
                "source_term": src_term,
                "target_lang": tgt_lang,
                "target_term": tgt_term,
                "domain": str(row.get("domain", "")).strip(),
                "priority": str(row.get("priority", "")).strip(),
                "case_sensitive": False,
                "match_type": str(row.get("match_type", "exact")).strip() or "exact",
                "note": str(row.get("note", "")).strip(),
                "alias": aliases,
                "tcr_scope": tcr_scope,
                "acceptance_scope": str(row.get("acceptance_scope", "")).strip(),
            }
            terms.append(term)

    return terms


# ── I/O helpers ─────────────────────────────────────────────────────────────

def read_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        raise FileNotFoundError(f"Input JSONL file not found: {path}")
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON at {path}, line {line_no}: {e}") from e
    return records


def first_existing_field(record: Dict, candidates: List[str]) -> Optional[str]:
    for field in candidates:
        if field in record:
            return field
    return None


def get_value(record: Dict, candidates: List[str], default: str = "") -> str:
    field = first_existing_field(record, candidates)
    if field is None:
        return default
    return str(record.get(field, "") or "")


def get_record_id(record: Dict, lang: str, index: int) -> str:
    value = get_value(record, ID_FIELD_CANDIDATES, "")
    if value:
        return value
    return f"{lang}_{index:06d}"


# ── Text matching utilities ─────────────────────────────────────────────────

ALPHABETIC_LANGS = {
    "en", "es", "de", "fr", "pt", "it", "nl", "no", "sv", "vi", "id", "ms"
}


def normalize_for_match(text: str, case_sensitive: bool) -> str:
    text = str(text or "")
    if case_sensitive:
        return text
    return text.lower()


def text_contains_term(text: str, term_text: str, lang: str, case_sensitive: bool = False) -> bool:
    """Check if term_text appears as a whole word/phrase in text."""
    if not text or not term_text:
        return False

    text_m = normalize_for_match(text, case_sensitive)
    term_m = normalize_for_match(term_text, case_sensitive)

    if lang in ALPHABETIC_LANGS:
        escaped = re.escape(term_m)
        pattern = rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"
        return re.search(pattern, text_m) is not None

    return term_m in text_m


def text_contains_any_alias(text: str, aliases: List[str], lang: str) -> bool:
    """Check if any alias appears in text."""
    for alias in aliases:
        if text_contains_term(text, alias, lang, case_sensitive=False):
            return True
    return False


def find_partial_match(expected: str, text: str, min_ratio: float = 0.5) -> bool:
    """Check if a substantial substring of expected appears in text."""
    expected = str(expected or "").strip()
    text = str(text or "")
    if not expected or not text or len(expected) < 2:
        return False

    min_len = max(2, int(len(expected) * min_ratio))

    # Try decreasing substring lengths
    for length in range(len(expected) - 1, min_len - 1, -1):
        for start in range(0, len(expected) - length + 1):
            partial = expected[start:start + length]
            if partial and partial in text and partial != expected:
                return True
    return False


def find_any_partial_match(candidates: List[str], text: str, min_ratio: float = 0.5) -> bool:
    """Check if any candidate has a substantial partial match in text."""
    for candidate in candidates:
        if find_partial_match(candidate, text, min_ratio):
            return True
    return False


# ── Source-term existence check ─────────────────────────────────────────────

def source_term_in_text(text: str, term: Dict) -> bool:
    """Check if the source_term appears in the source text."""
    src_term = str(term.get("source_term", "") or "")
    src_lang = str(term.get("source_lang", "") or "")
    case_sensitive = bool(term.get("case_sensitive", False))
    return text_contains_term(text, src_term, src_lang, case_sensitive)


# ── Dual-mode error classification ──────────────────────────────────────────

def classify_term_strict(term: Dict, mt_text: str) -> Tuple[str, bool]:
    """
    Strict classification: only exact match of target_term counts as correct.
    Distinguishes error types for diagnostic purposes while keeping TCR strict.

    Returns (error_type, is_correct).
    """
    target_term = str(term.get("target_term", "") or "").strip()
    target_lang = str(term.get("target_lang", "") or "zh")
    source_term = str(term.get("source_term", "") or "").strip()

    mt = str(mt_text or "").strip()
    if not mt:
        return "missing", False

    # Exact match of target_term → correct
    if text_contains_term(mt, target_term, target_lang, case_sensitive=False):
        return "no_error", True

    # Partial match of target_term → partial_match error
    if find_partial_match(target_term, mt, min_ratio=0.5):
        return "partial_match", False

    # Short/ambiguous terms
    if len(target_term) <= 1 or len(source_term) <= 2:
        return "ambiguous", False

    return "missing", False


def classify_term_relaxed(term: Dict, mt_text: str) -> Tuple[str, bool]:
    """
    Relaxed classification: accepts target_term, alias, or reasonable variant.
    Partial matches and alias matches count as correct.

    Returns (error_type, is_correct).
    """
    target_term = str(term.get("target_term", "") or "").strip()
    target_lang = str(term.get("target_lang", "") or "zh")
    aliases = term.get("alias", []) or []
    source_term = str(term.get("source_term", "") or "").strip()

    mt = str(mt_text or "").strip()
    if not mt:
        return "missing", False

    # 1. Exact match of target_term
    if text_contains_term(mt, target_term, target_lang, case_sensitive=False):
        return "no_error", True

    # 2. Exact match of any alias
    if aliases and text_contains_any_alias(mt, aliases, target_lang):
        return "no_error", True

    # 3. Partial match of target_term or alias (reasonable variant)
    all_accepted = [target_term] + aliases
    if find_any_partial_match(all_accepted, mt, min_ratio=0.5):
        return "no_error", True  # In relaxed mode, partial matches are acceptable

    # 4. Short terms — ambiguous rather than wrong
    if len(target_term) <= 1 or len(source_term) <= 2:
        return "ambiguous", False

    return "missing", False


def classify_term_detailed(
    term: Dict,
    mt_text: str,
    all_terms: List[Dict],
) -> Dict:
    """
    Full classification returning both strict and relaxed verdicts,
    plus a detailed error type for diagnostic purposes.

    The detailed_error_type is based on the relaxed classification's
    diagnostic view: was the term missing entirely, partially matched,
    or just ambiguous?
    """
    target_term = str(term.get("target_term", "") or "").strip()
    target_lang = str(term.get("target_lang", "") or "zh")
    aliases = term.get("alias", []) or []
    source_term = str(term.get("source_term", "") or "").strip()
    mt = str(mt_text or "").strip()

    # Strict verdict
    strict_type, strict_correct = classify_term_strict(term, mt_text)

    # Relaxed verdict
    relaxed_type, relaxed_correct = classify_term_relaxed(term, mt_text)

    # Detailed diagnostic error type
    if relaxed_correct:
        if strict_correct:
            detailed_type = "no_error"
        elif aliases and text_contains_any_alias(mt, aliases, target_lang):
            detailed_type = "alias_match"  # correct via alias, strict missed
        else:
            detailed_type = "partial_match_ok"  # correct via partial match
    else:
        # Determine specific diagnostic error
        if not mt:
            detailed_type = "missing"
        elif find_partial_match(target_term, mt, min_ratio=0.3):
            detailed_type = "partial_match"  # partial match found but not enough
        elif len(target_term) <= 1 or len(source_term) <= 2:
            detailed_type = "ambiguous"
        else:
            detailed_type = "missing"

    return {
        "strict_error_type": strict_type,
        "strict_correct": strict_correct,
        "relaxed_error_type": relaxed_type,
        "relaxed_correct": relaxed_correct,
        "detailed_error_type": detailed_type,
    }


# ── Build detail row ────────────────────────────────────────────────────────

def build_detail_row(
    lang: str,
    target_lang: str,
    record_id: str,
    source_text: str,
    mt_text: str,
    term: Dict,
    classification: Dict,
) -> Dict:
    return {
        "lang_pair": f"{lang}2{target_lang}",
        "segment_id": record_id,
        "source_text": source_text,
        "mt_text": mt_text,
        "source_term": term.get("source_term", ""),
        "expected_target_term": term.get("target_term", ""),
        "aliases": "; ".join(term.get("alias", []) or []),
        "tcr_scope": term.get("tcr_scope", ""),
        "acceptance_scope": term.get("acceptance_scope", ""),
        "term_priority": term.get("priority", ""),
        "term_id": term.get("term_id", ""),
        "domain": term.get("domain", ""),
        "src_lang": lang,
        "strict_correct": classification["strict_correct"],
        "relaxed_correct": classification["relaxed_correct"],
        "strict_error_type": classification["strict_error_type"],
        "relaxed_error_type": classification["relaxed_error_type"],
        "detailed_error_type": classification["detailed_error_type"],
    }


# ── Per-language processing ─────────────────────────────────────────────────

def check_records_for_lang_v03(
    lang: str,
    mt_path: Path,
    termbase_path: str,
    target_lang: str,
) -> Dict:
    """Run dual-metric TCR check for one language."""
    terms = load_terms_v03(
        termbase_path=termbase_path,
        source_lang=lang,
        target_lang=target_lang,
    )

    strict_terms = [t for t in terms if t.get("tcr_scope") == "strict"]
    relaxed_terms = [t for t in terms if t.get("tcr_scope") in ("strict", "relaxed")]

    records = read_jsonl(mt_path)

    detail_rows: List[Dict] = []
    error_rows_strict: List[Dict] = []
    error_rows_relaxed: List[Dict] = []

    # Counters for strict scope (external acceptance)
    strict_total = 0
    strict_correct = 0
    # Counters for all terms (internal diagnosis, relaxed)
    relaxed_total = 0
    relaxed_correct = 0
    # Counters for core high terms only (strict scope, strict matching)
    core_total = 0
    core_correct = 0

    # Error type counters
    strict_error_counts = {et: 0 for et in ERROR_TYPES}
    relaxed_error_counts = {et: 0 for et in ERROR_TYPES}

    records_with_prediction = 0

    for index, record in enumerate(records, start=1):
        record_id = get_record_id(record, lang, index)
        source_text = get_value(record, SOURCE_FIELD_CANDIDATES, "")
        mt_text = get_value(record, PREDICTION_FIELD_CANDIDATES, "")

        if mt_text:
            records_with_prediction += 1

        for term in terms:
            # Check if source term appears in source text
            if not source_term_in_text(source_text, term):
                continue

            classification = classify_term_detailed(term, mt_text, terms)
            tcr_scope = term.get("tcr_scope", "")

            row = build_detail_row(
                lang=lang,
                target_lang=target_lang,
                record_id=record_id,
                source_text=source_text,
                mt_text=mt_text,
                term=term,
                classification=classification,
            )
            detail_rows.append(row)

            # Strict scope metrics
            if tcr_scope == "strict":
                strict_total += 1
                if classification["strict_correct"]:
                    strict_correct += 1
                else:
                    error_rows_strict.append(row)
                strict_error_counts[classification["strict_error_type"]] += 1

            # Core high terms (same as strict scope but tracked separately for clarity)
            if tcr_scope == "strict":
                core_total += 1
                if classification["strict_correct"]:
                    core_correct += 1

            # Relaxed (all terms) metrics
            relaxed_total += 1
            if classification["relaxed_correct"]:
                relaxed_correct += 1
            else:
                error_rows_relaxed.append(row)
            relaxed_error_counts[classification["relaxed_error_type"]] += 1

    # Compute rates
    strict_tcr = round(strict_correct / strict_total * 100, 2) if strict_total > 0 else 0.0
    relaxed_tcr = round(relaxed_correct / relaxed_total * 100, 2) if relaxed_total > 0 else 0.0
    core_tcr = round(core_correct / core_total * 100, 2) if core_total > 0 else 0.0

    # RFP target: stored as decimal (0.90) in lang_map, convert to percentage
    rfp_target_decimal = RFP_LANGUAGES.get(lang, {}).get("target", None)
    rfp_target_pct = round(rfp_target_decimal * 100, 0) if rfp_target_decimal else None

    def _rfp_gap(tcr: float) -> str:
        """Compute gap in percentage points. Returns '' if no RFP target."""
        if rfp_target_pct is None:
            return ""
        return round(tcr - rfp_target_pct, 2)

    summary = {
        "lang_pair": f"{lang}2{target_lang}",
        "src_lang": lang,
        "src_lang_name": get_lang_name(lang),
        "is_rfp_language": is_rfp_language(lang),
        "rfp_target_pct": rfp_target_pct if rfp_target_pct else "",
        "mt_file": str(mt_path),
        "total_records": len(records),
        "records_with_prediction": records_with_prediction,
        # Strict (external acceptance)
        "strict_loaded_terms": len(strict_terms),
        "strict_total_hits": strict_total,
        "strict_correct_hits": strict_correct,
        "strict_wrong_hits": strict_total - strict_correct,
        "strict_tcr": strict_tcr,
        "strict_missing": strict_error_counts["missing"],
        "strict_wrong_translation": strict_error_counts["wrong_translation"],
        "strict_partial_match": strict_error_counts["partial_match"],
        "strict_ambiguous": strict_error_counts["ambiguous"],
        "strict_no_error": strict_error_counts["no_error"],
        # Relaxed (internal diagnosis)
        "relaxed_loaded_terms": len(terms),
        "relaxed_total_hits": relaxed_total,
        "relaxed_correct_hits": relaxed_correct,
        "relaxed_wrong_hits": relaxed_total - relaxed_correct,
        "relaxed_tcr": relaxed_tcr,
        "relaxed_missing": relaxed_error_counts["missing"],
        "relaxed_wrong_translation": relaxed_error_counts["wrong_translation"],
        "relaxed_partial_match": relaxed_error_counts["partial_match"],
        "relaxed_ambiguous": relaxed_error_counts["ambiguous"],
        "relaxed_no_error": relaxed_error_counts["no_error"],
        # Core high terms
        "core_high_total_hits": core_total,
        "core_high_correct_hits": core_correct,
        "core_high_tcr": core_tcr,
        # RFP gap
        "strict_rfp_gap": _rfp_gap(strict_tcr),
        "relaxed_rfp_gap": _rfp_gap(relaxed_tcr),
        "core_rfp_gap": _rfp_gap(core_tcr),
        "status": "ok",
    }

    return {
        "summary": summary,
        "details": detail_rows,
        "errors_strict": error_rows_strict,
        "errors_relaxed": error_rows_relaxed,
    }


# ── MT file finder ──────────────────────────────────────────────────────────

def find_mt_file(mt_root: Path, model: str, lang: str, target_lang: str) -> Optional[Path]:
    model_dir = mt_root / model
    candidates = [
        model_dir / f"mt_{lang}_{target_lang}_{model}.jsonl",
        model_dir / f"mt_{lang}_{target_lang}.{model}.jsonl",
        model_dir / f"mt_{lang}_{target_lang}_{model.replace('-', '_')}.jsonl",
        model_dir / f"mt_{lang}._{model}.jsonl",
        model_dir / f"mt_{lang}_{model}.jsonl",
        mt_root / f"mt_{lang}_{target_lang}_{model}.jsonl",
        mt_root / f"mt_{lang}._{model}.jsonl",
        mt_root / f"mt_{lang}_{model}.jsonl",
    ]
    for path in candidates:
        if path.exists():
            return path

    glob_patterns = [
        f"mt_{lang}*{model}*.jsonl",
        f"*{lang}*{model}*.jsonl",
        f"mt_{lang}*.jsonl",
        f"{lang}*.jsonl",
    ]
    search_dirs = [model_dir, mt_root]
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for pattern in glob_patterns:
            matches = sorted(search_dir.glob(pattern))
            if matches:
                return matches[0]
    return None


# ── Missing summary ─────────────────────────────────────────────────────────

def build_missing_summary(lang: str, target_lang: str) -> Dict:
    rfp_target_decimal = RFP_LANGUAGES.get(lang, {}).get("target", None)
    rfp_target_pct = round(rfp_target_decimal * 100, 0) if rfp_target_decimal else ""

    template = {
        "lang_pair": f"{lang}2{target_lang}",
        "src_lang": lang,
        "src_lang_name": get_lang_name(lang),
        "is_rfp_language": is_rfp_language(lang),
        "rfp_target_pct": rfp_target_pct,
        "mt_file": "",
        "total_records": 0,
        "records_with_prediction": 0,
        "status": "mt_file_missing",
    }
    for prefix in ["strict", "relaxed"]:
        template.update({
            f"{prefix}_loaded_terms": 0,
            f"{prefix}_total_hits": 0,
            f"{prefix}_correct_hits": 0,
            f"{prefix}_wrong_hits": 0,
            f"{prefix}_tcr": 0.0,
            f"{prefix}_missing": 0,
            f"{prefix}_wrong_translation": 0,
            f"{prefix}_partial_match": 0,
            f"{prefix}_ambiguous": 0,
            f"{prefix}_no_error": 0,
            f"{prefix}_rfp_gap": "",
        })
    template.update({
        "core_high_total_hits": 0,
        "core_high_correct_hits": 0,
        "core_high_tcr": 0.0,
        "core_rfp_gap": "",
    })
    return template


# ── Sample review for error calibration ─────────────────────────────────────

def generate_error_samples(
    error_rows: List[Dict],
    n_per_type: int = 5,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generate stratified random samples of error rows for manual review.
    Samples n_per_type from each error type (missing, partial_match, wrong_translation).
    """
    import random
    random.seed(seed)

    samples = []
    for error_type in ["missing", "wrong_translation", "partial_match", "ambiguous"]:
        pool = [r for r in error_rows if r.get("detailed_error_type") == error_type]
        if not pool:
            continue
        n = min(n_per_type, len(pool))
        sampled = random.sample(pool, n)
        for r in sampled:
            r_copy = dict(r)
            r_copy["sample_category"] = error_type
            samples.append(r_copy)

    if not samples:
        return pd.DataFrame()

    cols = [
        "sample_category", "src_lang", "tcr_scope",
        "source_term", "expected_target_term", "aliases",
        "source_text", "mt_text",
        "strict_correct", "relaxed_correct",
        "strict_error_type", "relaxed_error_type", "detailed_error_type",
        "segment_id", "term_id", "domain",
    ]
    df = pd.DataFrame(samples)
    return df[[c for c in cols if c in df.columns]]


# ── Excel report writer ─────────────────────────────────────────────────────

def save_excel_report_v03(
    summary_rows: List[Dict],
    detail_rows: List[Dict],
    error_rows_strict: List[Dict],
    error_rows_relaxed: List[Dict],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary_df = pd.DataFrame(summary_rows)

    # Sort RFP languages first
    rfp_order = {lang: i for i, lang in enumerate(RFP_LANGS)}
    summary_df["_rfp_rank"] = summary_df["src_lang"].map(
        lambda x: rfp_order.get(x, 99)
    )
    summary_df = summary_df.sort_values(
        by=["_rfp_rank", "strict_tcr"], ascending=[True, False]
    ).drop(columns=["_rfp_rank"]).reset_index(drop=True)

    details_df = pd.DataFrame(detail_rows)
    errors_strict_df = pd.DataFrame(error_rows_strict)
    errors_relaxed_df = pd.DataFrame(error_rows_relaxed)

    # Sample review
    sample_df = generate_error_samples(error_rows_relaxed, n_per_type=5)

    # RFP summary
    rfp_summary_df = summary_df[summary_df["is_rfp_language"] == True].copy()

    # Core high terms breakdown
    core_breakdown_rows = []
    grouped: Dict[Tuple[str, str], Dict] = {}
    for row in detail_rows:
        if row.get("tcr_scope") != "strict":
            continue
        key = (row.get("src_lang", ""), row.get("source_term", ""))
        if key not in grouped:
            grouped[key] = {
                "src_lang": row.get("src_lang", ""),
                "source_term": row.get("source_term", ""),
                "expected_target_term": row.get("expected_target_term", ""),
                "domain": row.get("domain", ""),
                "total_hits": 0,
                "strict_correct": 0,
                "relaxed_correct": 0,
            }
        g = grouped[key]
        g["total_hits"] += 1
        if row.get("strict_correct"):
            g["strict_correct"] += 1
        if row.get("relaxed_correct"):
            g["relaxed_correct"] += 1

    for item in grouped.values():
        total = item["total_hits"]
        item["strict_tcr"] = round(item["strict_correct"] / total * 100, 2) if total else 0.0
        item["relaxed_tcr"] = round(item["relaxed_correct"] / total * 100, 2) if total else 0.0
        core_breakdown_rows.append(item)

    core_breakdown_df = pd.DataFrame(core_breakdown_rows)
    if not core_breakdown_df.empty:
        core_breakdown_df = core_breakdown_df.sort_values(
            by=["src_lang", "total_hits", "source_term"],
            ascending=[True, False, True],
        ).reset_index(drop=True)

    detail_cols = [
        "lang_pair", "segment_id", "source_text", "mt_text",
        "source_term", "expected_target_term", "aliases",
        "tcr_scope", "acceptance_scope",
        "strict_correct", "relaxed_correct",
        "strict_error_type", "relaxed_error_type", "detailed_error_type",
        "term_priority", "term_id", "domain", "src_lang",
    ]

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # Sheet 1: Summary by language (dual metrics)
        summary_df.to_excel(writer, sheet_name="summary_by_lang", index=False)

        # Sheet 2: RFP languages summary
        rfp_summary_df.to_excel(writer, sheet_name="rfp_summary", index=False)

        # Sheet 3: Core high terms breakdown
        core_breakdown_df.to_excel(writer, sheet_name="core_high_breakdown", index=False)

        # Sheet 4: Detail by segment
        details_df[[c for c in detail_cols if c in details_df.columns]].to_excel(
            writer, sheet_name="detail_by_segment", index=False
        )

        # Sheet 5: Strict errors
        if not errors_strict_df.empty:
            errors_strict_df[[c for c in detail_cols if c in errors_strict_df.columns]].to_excel(
                writer, sheet_name="errors_strict", index=False
            )

        # Sheet 6: Relaxed errors
        if not errors_relaxed_df.empty:
            errors_relaxed_df[[c for c in detail_cols if c in errors_relaxed_df.columns]].to_excel(
                writer, sheet_name="errors_relaxed", index=False
            )

        # Sheet 7: Sample review
        if not sample_df.empty:
            sample_df.to_excel(writer, sheet_name="sample_review", index=False)

    # Auto-adjust column widths
    for sheet_name in writer.sheets:
        ws = writer.sheets[sheet_name]
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                try:
                    val = str(cell.value or "")
                    max_len = max(max_len, len(val))
                except Exception:
                    pass
            ws.column_dimensions[col_letter].width = min(max_len + 2, 60)


# ── Terminal report ─────────────────────────────────────────────────────────

def print_summary_table(
    summary_rows: List[Dict],
    title: str,
    metric_key: str = "strict_tcr",
    tcr_label: str = "Strict TCR",
) -> None:
    """Print a formatted summary table."""
    print()
    print("=" * 110)
    print(f"  {title}")
    print("=" * 110)

    header = (
        f"{'Lang':<8} {'Lang Name':<14} {'Terms':>6} {'Hits':>6} {'Correct':>8} "
        f"{tcr_label:>10} {'RFP Target':>11} {'Gap':>8} {'Status':>8}"
    )
    print(header)
    print("-" * 110)

    for row in summary_rows:
        if row.get("status") == "mt_file_missing":
            continue
        lang = row["src_lang"]
        name = row["src_lang_name"]
        # Determine which 'loaded_terms' key to use based on metric
        if metric_key == "relaxed_tcr":
            loaded = row.get("relaxed_loaded_terms", 0)
        else:
            loaded = row.get("strict_loaded_terms", 0)
        # Determine hit/correct keys
        if metric_key == "relaxed_tcr":
            hits = row.get("relaxed_total_hits", 0)
            correct = row.get("relaxed_correct_hits", 0)
        elif metric_key == "core_high_tcr":
            hits = row.get("core_high_total_hits", 0)
            correct = row.get("core_high_correct_hits", 0)
        else:
            hits = row.get("strict_total_hits", 0)
            correct = row.get("strict_correct_hits", 0)

        tcr = row.get(metric_key, 0.0)
        target_pct = row.get("rfp_target_pct", "")
        # Determine gap key
        if metric_key == "relaxed_tcr":
            gap = row.get("relaxed_rfp_gap", "")
        elif metric_key == "core_high_tcr":
            gap = row.get("core_rfp_gap", "")
        else:
            gap = row.get("strict_rfp_gap", "")

        if target_pct and target_pct != "":
            target_val = float(target_pct)
            if tcr >= target_val:
                status = "✅ PASS"
            elif tcr >= target_val - 5:
                status = "⚠️ MARGIN"
            else:
                status = "❌ FAIL"
            target_str = f"{target_val:.0f}%"
            gap_str = f"{gap:+.2f}pp" if gap != "" else ""
        else:
            status = "—"
            target_str = "—"
            gap_str = "—"

        flag = "🔴" if row.get("is_rfp_language") else "  "
        print(
            f"{flag} {lang:<5} {name:<14} {loaded:>6} {hits:>6} {correct:>8} "
            f"{tcr:>9.2f}% {target_str:>10} {gap_str:>8} {status:>8}"
        )

    print("-" * 110)


def print_error_breakdown(summary_rows: List[Dict], metric_prefix: str, title: str) -> None:
    """Print error type distribution."""
    print()
    print(f"  {title} — Error Type Distribution:")
    print(f"  {'Lang':<8} {'missing':>10} {'wrong_trans':>12} {'partial':>10} {'ambiguous':>10}")
    print(f"  {'—'*8} {'—'*10} {'—'*12} {'—'*10} {'—'*10}")
    for row in summary_rows:
        if row.get("status") == "mt_file_missing":
            continue
        print(
            f"  {row['src_lang']:<8} "
            f"{row.get(f'{metric_prefix}_missing', 0):>10} "
            f"{row.get(f'{metric_prefix}_wrong_translation', 0):>12} "
            f"{row.get(f'{metric_prefix}_partial_match', 0):>10} "
            f"{row.get(f'{metric_prefix}_ambiguous', 0):>10}"
        )


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TCR V0.3 — Dual-metric term consistency checker (strict + relaxed)."
    )
    parser.add_argument(
        "--langs", nargs="+", default=LANGS,
        help="Language list.",
    )
    parser.add_argument(
        "--model", default="qwen-max",
        help="MT model name used in output filenames.",
    )
    parser.add_argument(
        "--mt-root", default="data/mt/qwen-max-term",
        help="MT root directory containing translation JSONL files.",
    )
    parser.add_argument(
        "--termbase", default="termbase/core_high_terms_v0.3_candidate.csv",
        help="V0.3 core high terms CSV path.",
    )
    parser.add_argument(
        "--target-lang", default="zh",
        help="Target language.",
    )
    parser.add_argument(
        "--output", default="data/report/termbase/term_consistency_v0.3.xlsx",
        help="Output Excel report path.",
    )
    parser.add_argument(
        "--inspect", action="store_true",
        help="Inspect first record fields for each MT file.",
    )
    args = parser.parse_args()

    mt_root = Path(args.mt_root)
    if not mt_root.is_absolute():
        mt_root = PROJECT_ROOT / mt_root

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    termbase_path = Path(args.termbase)
    if not termbase_path.is_absolute():
        termbase_path = PROJECT_ROOT / termbase_path

    if not termbase_path.exists():
        print(f"ERROR: Termbase not found: {termbase_path}")
        print("Run scripts/termbase/build_core_high_terms_v0.3.py first.")
        return 1

    summary_rows = []
    detail_rows = []
    error_rows_strict = []
    error_rows_relaxed = []

    for lang in args.langs:
        mt_path = find_mt_file(
            mt_root=mt_root, model=args.model,
            lang=lang, target_lang=args.target_lang,
        )

        print("=" * 80)
        print(f"V0.3 TCR — Language: {lang} ({get_lang_name(lang)})")

        if mt_path is None:
            print(f"MT file not found for language: {lang}")
            summary = build_missing_summary(lang, args.target_lang)
            summary_rows.append(summary)
            continue

        print(f"MT file: {mt_path}")

        if args.inspect:
            records = read_jsonl(mt_path)
            if records:
                first = records[0]
                print(f"First record keys: {list(first.keys())}")
                sf = first_existing_field(first, SOURCE_FIELD_CANDIDATES)
                pf = first_existing_field(first, PREDICTION_FIELD_CANDIDATES)
                print(f"Source field: {sf}")
                print(f"Prediction field: {pf}")

        result = check_records_for_lang_v03(
            lang=lang,
            mt_path=mt_path,
            termbase_path=str(termbase_path),
            target_lang=args.target_lang,
        )

        summary = result["summary"]
        summary["status"] = "ok"
        summary_rows.append(summary)
        detail_rows.extend(result["details"])
        error_rows_strict.extend(result["errors_strict"])
        error_rows_relaxed.extend(result["errors_relaxed"])

        print(f"  Records: {summary['total_records']} (with prediction: {summary['records_with_prediction']})")
        print(f"  Terms loaded: strict={summary['strict_loaded_terms']}, all={summary['relaxed_loaded_terms']}")
        print(f"  Strict TCR:  {summary['strict_tcr']}%  (hits={summary['strict_total_hits']}, correct={summary['strict_correct_hits']})")
        print(f"  Relaxed TCR: {summary['relaxed_tcr']}%  (hits={summary['relaxed_total_hits']}, correct={summary['relaxed_correct_hits']})")
        print(f"  Core High TCR: {summary['core_high_tcr']}%  (hits={summary['core_high_total_hits']}, correct={summary['core_high_correct_hits']})")
        rfp_target_pct = summary.get("rfp_target_pct")
        if rfp_target_pct:
            print(f"  RFP Target: {rfp_target_pct:.0f}%")
            print(f"    Strict gap:  {summary['strict_rfp_gap']:+.2f}pp")
            print(f"    Relaxed gap: {summary['relaxed_rfp_gap']:+.2f}pp")
            print(f"    Core gap:    {summary['core_rfp_gap']:+.2f}pp")

    # ── Print summary tables ─────────────────────────────────────────────────

    # Sort: RFP first, then by strict TCR
    rfp_order = {lang: i for i, lang in enumerate(RFP_LANGS)}
    sorted_summaries = sorted(
        summary_rows,
        key=lambda r: (rfp_order.get(r["src_lang"], 99), -r.get("strict_tcr", 0)),
    )

    # Only show rows that actually ran
    active = [r for r in sorted_summaries if r.get("status") != "mt_file_missing"]

    print_summary_table(active, "STRICT TCR — External Acceptance (core high terms, exact match only)", metric_key="strict_tcr", tcr_label="Strict TCR")
    print_error_breakdown(active, "strict", "STRICT")

    print_summary_table(active, "RELAXED TCR — Internal Diagnosis (all terms, alias + variants allowed)", metric_key="relaxed_tcr", tcr_label="Relaxed TCR")
    print_error_breakdown(active, "relaxed", "RELAXED")

    print_summary_table(active, "CORE HIGH TCR — Strict Scope, Strict Matching", metric_key="core_high_tcr", tcr_label="Core High TCR")

    # ── RFP-focused summary ──────────────────────────────────────────────────
    print()
    print("=" * 110)
    print("  RFP LANGUAGE COMPLIANCE SUMMARY")
    print("=" * 110)
    rfp_active = [r for r in active if r.get("is_rfp_language")]
    pass_count_strict = 0
    pass_count_relaxed = 0
    for r in rfp_active:
        target_pct = r.get("rfp_target_pct")
        if target_pct and target_pct != "":
            target_val = float(target_pct)
            strict_tcr = r.get("strict_tcr", 0)
            relaxed_tcr = r.get("relaxed_tcr", 0)
            core_tcr = r.get("core_high_tcr", 0)

            if strict_tcr >= target_val:
                pass_count_strict += 1
            if relaxed_tcr >= target_val:
                pass_count_relaxed += 1

            status_strict = "✅ PASS" if strict_tcr >= target_val else ("⚠️ MARGIN" if strict_tcr >= target_val - 5 else "❌ FAIL")
            status_relaxed = "✅ PASS" if relaxed_tcr >= target_val else ("⚠️ MARGIN" if relaxed_tcr >= target_val - 5 else "❌ FAIL")

            strict_gap = r.get("strict_rfp_gap", "")
            relaxed_gap = r.get("relaxed_rfp_gap", "")
            core_gap = r.get("core_rfp_gap", "")

            gap_str_strict = f"({strict_gap:+.1f}pp)" if strict_gap != "" else ""
            gap_str_relaxed = f"({relaxed_gap:+.1f}pp)" if relaxed_gap != "" else ""
            gap_str_core = f"({core_gap:+.1f}pp)" if core_gap != "" else ""

            print(
                f"  {r['src_lang']:<5} ({r['src_lang_name']:<12}) "
                f"Target: {target_val:.0f}% | "
                f"Strict: {strict_tcr:.1f}% {gap_str_strict} {status_strict} | "
                f"Relaxed: {relaxed_tcr:.1f}% {gap_str_relaxed} {status_relaxed} | "
                f"Core: {core_tcr:.1f}% {gap_str_core}"
            )
    print(f"  Strict pass: {pass_count_strict}/{len(rfp_active)} | Relaxed pass: {pass_count_relaxed}/{len(rfp_active)}")

    # ── Save Excel report ────────────────────────────────────────────────────
    save_excel_report_v03(
        summary_rows=active,
        detail_rows=detail_rows,
        error_rows_strict=error_rows_strict,
        error_rows_relaxed=error_rows_relaxed,
        output_path=output_path,
    )
    print()
    print("=" * 80)
    print(f"V0.3 Report saved to: {output_path}")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
