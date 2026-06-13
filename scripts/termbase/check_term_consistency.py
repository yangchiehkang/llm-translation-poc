import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.termbase.load_terms import load_terms
from scripts.utils.lang_map import RFP_LANGUAGES, get_lang_name, is_rfp_language


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
    "source",
    "src",
    "src_text",
    "source_text",
    "text",
    "input",
    "sentence",
    "segment",
    "source_sentence",
]

PREDICTION_FIELD_CANDIDATES = [
    "mt_text",
    "prediction",
    "pred",
    "translation",
    "mt",
    "hypothesis",
    "output",
    "target",
    "target_text",
    "translated_text",
]

ID_FIELD_CANDIDATES = [
    "id",
    "seg_id",
    "sample_id",
    "sentence_id",
    "uid",
]


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
                raise ValueError(
                    f"Invalid JSON at {path}, line {line_no}: {e}"
                ) from e

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


def normalize_for_match(text: str, case_sensitive: bool) -> str:
    text = str(text or "")

    if case_sensitive:
        return text

    return text.lower()


def term_exists_in_text(text: str, term: Dict, use_source_lang: bool = True) -> bool:
    if use_source_lang:
        term_text = str(term.get("source_term", "") or "")
        lang = str(term.get("source_lang", "") or "")
    else:
        term_text = str(term.get("target_term", "") or "")
        lang = str(term.get("target_lang", "") or "")

    case_sensitive = bool(term.get("case_sensitive", False))

    if not text or not term_text:
        return False

    text_for_match = normalize_for_match(text, case_sensitive)
    term_for_match = normalize_for_match(term_text, case_sensitive)

    alphabetic_langs = {
        "en", "es", "de", "fr", "pt", "it", "nl", "no", "sv", "vi", "id", "ms"
    }

    if lang in alphabetic_langs:
        escaped = re.escape(term_for_match)
        pattern = rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"
        return re.search(pattern, text_for_match) is not None

    return term_for_match in text_for_match


def find_partial_target_match(expected_target: str, mt_text: str) -> bool:
    expected = str(expected_target or "").strip()
    mt = str(mt_text or "")

    if not expected or not mt or len(expected) < 2:
        return False

    min_len = max(2, len(expected) // 2)

    for length in range(len(expected) - 1, min_len - 1, -1):
        for start in range(0, len(expected) - length + 1):
            partial = expected[start:start + length]
            if partial and partial in mt and partial != expected:
                return True

    return False


def find_wrong_translation_hint(
    source_term: str,
    expected_target: str,
    mt_text: str,
    all_terms: List[Dict],
) -> bool:
    mt = str(mt_text or "").strip()

    if not mt:
        return False

    source_term_norm = normalize_for_match(source_term, False)

    for term in all_terms:
        other_source = normalize_for_match(term.get("source_term", ""), False)
        other_target = str(term.get("target_term", "") or "").strip()

        if not other_source or not other_target:
            continue

        if other_source == source_term_norm:
            continue

        if other_target == expected_target:
            continue

        if other_source in source_term_norm or source_term_norm in other_source:
            if other_target in mt and expected_target not in mt:
                return True

    return False


def classify_term_error(
    term: Dict,
    mt_text: str,
    all_terms: List[Dict],
) -> Tuple[str, bool]:
    expected_target = str(term.get("target_term", "") or "").strip()
    source_term = str(term.get("source_term", "") or "").strip()

    if term_exists_in_text(mt_text, term, use_source_lang=False):
        return "no_error", True

    if not str(mt_text or "").strip():
        return "missing", False

    if find_partial_target_match(expected_target, mt_text):
        return "partial_match", False

    if find_wrong_translation_hint(source_term, expected_target, mt_text, all_terms):
        return "wrong_translation", False

    if len(expected_target) <= 1 or len(source_term) <= 2:
        return "ambiguous", False

    if " " in source_term and len(source_term.split()) >= 2:
        source_words = [w for w in source_term.split() if len(w) > 2]
        if source_words and not find_partial_target_match(expected_target, mt_text):
            return "wrong_translation", False

    return "missing", False


def make_lang_pair(src_lang_code: str, target_lang: str) -> str:
    return f"{src_lang_code}2{target_lang}"


def build_detail_row(
    lang: str,
    target_lang: str,
    record_id: str,
    source_text: str,
    mt_text: str,
    term: Dict,
    error_type: str,
    is_term_correct: bool,
) -> Dict:
    return {
        "lang_pair": make_lang_pair(lang, target_lang),
        "segment_id": record_id,
        "source_text": source_text,
        "mt_text": mt_text,
        "source_term": term.get("source_term", ""),
        "expected_target_term": term.get("target_term", ""),
        "is_term_matched": True,
        "is_term_correct": is_term_correct,
        "error_type": error_type,
        "term_priority": term.get("priority", ""),
        "term_id": term.get("term_id", ""),
        "domain": term.get("domain", ""),
        "src_lang": lang,
    }


def count_error_types(rows: List[Dict]) -> Dict[str, int]:
    counts = {error_type: 0 for error_type in ERROR_TYPES}

    for row in rows:
        error_type = row.get("error_type", "")
        if error_type in counts:
            counts[error_type] += 1

    return counts


def check_records_for_lang(
    lang: str,
    mt_path: Path,
    termbase_path: str,
    target_lang: str,
) -> Dict:
    terms = load_terms(
        termbase_path=termbase_path,
        source_lang=lang,
        target_lang=target_lang,
    )

    records = read_jsonl(mt_path)

    detail_rows = []
    error_rows = []
    high_priority_rows = []

    total_term_hits = 0
    correct_term_hits = 0
    wrong_term_hits = 0
    records_with_prediction = 0

    for index, record in enumerate(records, start=1):
        record_id = get_record_id(record, lang, index)

        source_text = get_value(record, SOURCE_FIELD_CANDIDATES, "")
        mt_text = get_value(record, PREDICTION_FIELD_CANDIDATES, "")

        if mt_text:
            records_with_prediction += 1

        for term in terms:
            source_hit = term_exists_in_text(
                text=source_text,
                term=term,
                use_source_lang=True,
            )

            if not source_hit:
                continue

            total_term_hits += 1

            error_type, is_term_correct = classify_term_error(
                term=term,
                mt_text=mt_text,
                all_terms=terms,
            )

            if is_term_correct:
                correct_term_hits += 1
            else:
                wrong_term_hits += 1

            row = build_detail_row(
                lang=lang,
                target_lang=target_lang,
                record_id=record_id,
                source_text=source_text,
                mt_text=mt_text,
                term=term,
                error_type=error_type,
                is_term_correct=is_term_correct,
            )

            detail_rows.append(row)

            if not is_term_correct:
                error_rows.append(row)

            if str(term.get("priority", "")).strip().lower() == "high":
                high_priority_rows.append(row)

    rate = (
        correct_term_hits / total_term_hits * 100
        if total_term_hits > 0
        else 0.0
    )

    error_type_counts = count_error_types(detail_rows)

    summary_row = {
        "lang_pair": make_lang_pair(lang, target_lang),
        "src_lang": lang,
        "src_lang_name": get_lang_name(lang),
        "is_rfp_language": is_rfp_language(lang),
        "mt_file": str(mt_path),
        "total_records": len(records),
        "records_with_prediction": records_with_prediction,
        "loaded_terms": len(terms),
        "total_term_hits": total_term_hits,
        "correct_term_hits": correct_term_hits,
        "wrong_term_hits": wrong_term_hits,
        "term_consistency_rate": round(rate, 2),
        "error_missing": error_type_counts["missing"],
        "error_wrong_translation": error_type_counts["wrong_translation"],
        "error_partial_match": error_type_counts["partial_match"],
        "error_ambiguous": error_type_counts["ambiguous"],
        "error_no_error": error_type_counts["no_error"],
    }

    high_priority_total = len(high_priority_rows)
    high_priority_correct = sum(
        1 for row in high_priority_rows if row["is_term_correct"]
    )
    high_priority_rate = (
        high_priority_correct / high_priority_total * 100
        if high_priority_total > 0
        else 0.0
    )

    summary_row["high_priority_total_hits"] = high_priority_total
    summary_row["high_priority_correct_hits"] = high_priority_correct
    summary_row["high_priority_tcr"] = round(high_priority_rate, 2)

    return {
        "summary": summary_row,
        "details": detail_rows,
        "errors": error_rows,
        "high_priority": high_priority_rows,
    }


def find_mt_file(mt_root: Path, model: str, lang: str, target_lang: str) -> Optional[Path]:
    model_dir = mt_root / model

    candidates = [
        model_dir / f"mt_{lang}_{target_lang}_{model}.jsonl",
        model_dir / f"mt_{lang}_{target_lang}.{model}.jsonl",
        model_dir / f"mt_{lang}_{target_lang}_{model.replace('-', '_')}.jsonl",
        model_dir / f"mt_{lang}._{model}.jsonl",
        model_dir / f"mt_{lang}_{model}.jsonl",
        model_dir / f"{lang}_{target_lang}_{model}.jsonl",
        model_dir / f"{lang}_{target_lang}.{model}.jsonl",
        model_dir / f"{lang}_{model}.jsonl",
        model_dir / f"{lang}.jsonl",
        mt_root / f"mt_{lang}_{target_lang}_{model}.jsonl",
        mt_root / f"mt_{lang}_{target_lang}.{model}.jsonl",
        mt_root / f"mt_{lang}._{model}.jsonl",
        mt_root / f"mt_{lang}_{model}.jsonl",
        mt_root / f"{lang}_{target_lang}_{model}.jsonl",
        mt_root / f"{lang}.jsonl",
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


def build_high_priority_summary(detail_rows: List[Dict]) -> pd.DataFrame:
    rows = []

    grouped: Dict[Tuple[str, str, str], Dict] = {}

    for row in detail_rows:
        if str(row.get("term_priority", "")).strip().lower() != "high":
            continue

        key = (
            row.get("src_lang", ""),
            row.get("source_term", ""),
            row.get("expected_target_term", ""),
        )

        if key not in grouped:
            grouped[key] = {
                "lang_pair": row.get("lang_pair", ""),
                "src_lang": row.get("src_lang", ""),
                "source_term": row.get("source_term", ""),
                "expected_target_term": row.get("expected_target_term", ""),
                "term_id": row.get("term_id", ""),
                "domain": row.get("domain", ""),
                "total_hits": 0,
                "correct_hits": 0,
                "wrong_hits": 0,
                "missing": 0,
                "wrong_translation": 0,
                "partial_match": 0,
                "ambiguous": 0,
            }

        item = grouped[key]
        item["total_hits"] += 1

        if row.get("is_term_correct"):
            item["correct_hits"] += 1
        else:
            item["wrong_hits"] += 1

        error_type = row.get("error_type", "")
        if error_type in item:
            item[error_type] += 1

    for item in grouped.values():
        total = item["total_hits"]
        item["term_consistency_rate"] = round(
            item["correct_hits"] / total * 100 if total else 0.0,
            2,
        )
        rows.append(item)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    return df.sort_values(
        by=["src_lang", "total_hits", "source_term"],
        ascending=[True, False, True],
    ).reset_index(drop=True)


def save_excel_report(
    summary_rows: List[Dict],
    detail_rows: List[Dict],
    error_rows: List[Dict],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary_df = pd.DataFrame(summary_rows)
    details_df = pd.DataFrame(detail_rows)
    errors_df = pd.DataFrame(error_rows)
    high_priority_df = build_high_priority_summary(detail_rows)

    detail_columns = [
        "lang_pair",
        "segment_id",
        "source_text",
        "mt_text",
        "source_term",
        "expected_target_term",
        "is_term_matched",
        "is_term_correct",
        "error_type",
        "term_priority",
        "term_id",
        "domain",
        "src_lang",
    ]

    error_columns = detail_columns

    if not details_df.empty:
        details_df = details_df[[c for c in detail_columns if c in details_df.columns]]
    if not errors_df.empty:
        errors_df = errors_df[[c for c in error_columns if c in errors_df.columns]]

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="summary_by_lang", index=False)
        details_df.to_excel(writer, sheet_name="detail_by_segment", index=False)
        errors_df.to_excel(writer, sheet_name="error_cases", index=False)
        high_priority_df.to_excel(writer, sheet_name="high_priority_terms", index=False)


def inspect_first_record(path: Path) -> None:
    records = read_jsonl(path)

    if not records:
        print("First record keys: []")
        return

    first = records[0]
    print(f"First record keys: {list(first.keys())}")

    source_field = first_existing_field(first, SOURCE_FIELD_CANDIDATES)
    prediction_field = first_existing_field(first, PREDICTION_FIELD_CANDIDATES)
    id_field = first_existing_field(first, ID_FIELD_CANDIDATES)

    print(f"Detected id field: {id_field}")
    print(f"Detected source field: {source_field}")
    print(f"Detected prediction field: {prediction_field}")

    if source_field:
        print(f"Source preview: {str(first.get(source_field, ''))[:160]}")

    if prediction_field:
        print(f"Prediction preview: {str(first.get(prediction_field, ''))[:160]}")


def build_missing_summary(lang: str, target_lang: str) -> Dict:
    return {
        "lang_pair": make_lang_pair(lang, target_lang),
        "src_lang": lang,
        "src_lang_name": get_lang_name(lang),
        "is_rfp_language": is_rfp_language(lang),
        "mt_file": "",
        "total_records": 0,
        "records_with_prediction": 0,
        "loaded_terms": 0,
        "total_term_hits": 0,
        "correct_term_hits": 0,
        "wrong_term_hits": 0,
        "term_consistency_rate": 0.0,
        "error_missing": 0,
        "error_wrong_translation": 0,
        "error_partial_match": 0,
        "error_ambiguous": 0,
        "error_no_error": 0,
        "high_priority_total_hits": 0,
        "high_priority_correct_hits": 0,
        "high_priority_tcr": 0.0,
        "status": "mt_file_missing",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Check term consistency (TCR) and export v0.2 Excel report."
    )

    parser.add_argument(
        "--langs",
        nargs="+",
        default=LANGS,
        help="Language list.",
    )

    parser.add_argument(
        "--model",
        default="qwen-max",
        help="MT model name used in output filenames.",
    )

    parser.add_argument(
        "--mt-root",
        default="data/mt/qwen-max-term",
        help="MT root directory containing translation JSONL files.",
    )

    parser.add_argument(
        "--termbase",
        default="termbase/auto_regulation_terms.csv",
        help="Termbase CSV path.",
    )

    parser.add_argument(
        "--target-lang",
        default="zh",
        help="Target language.",
    )

    parser.add_argument(
        "--output",
        default="data/report/termbase/term_consistency_v0.2.xlsx",
        help="Output Excel report path.",
    )

    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Inspect first record fields for each MT file.",
    )

    args = parser.parse_args()

    mt_root = Path(args.mt_root)
    output_path = Path(args.output)

    if not Path(args.termbase).exists():
        print(f"ERROR: Termbase not found: {args.termbase}")
        print("Please ensure termbase/auto_regulation_terms.csv exists before running.")
        return 1

    summary_rows = []
    detail_rows = []
    error_rows = []

    for lang in args.langs:
        mt_path = find_mt_file(
            mt_root=mt_root,
            model=args.model,
            lang=lang,
            target_lang=args.target_lang,
        )

        print("=" * 80)
        print(f"Language: {lang} ({get_lang_name(lang)})")

        if mt_path is None:
            print(f"MT file not found for language: {lang}")
            summary = build_missing_summary(lang, args.target_lang)
            summary_rows.append(summary)
            continue

        print(f"MT file: {mt_path}")

        if args.inspect:
            inspect_first_record(mt_path)

        result = check_records_for_lang(
            lang=lang,
            mt_path=mt_path,
            termbase_path=args.termbase,
            target_lang=args.target_lang,
        )

        summary = result["summary"]
        summary["status"] = "ok"

        summary_rows.append(summary)
        detail_rows.extend(result["details"])
        error_rows.extend(result["errors"])

        print(f"Total records: {summary['total_records']}")
        print(f"Records with prediction: {summary['records_with_prediction']}")
        print(f"Loaded terms: {summary['loaded_terms']}")
        print(f"Total term hits: {summary['total_term_hits']}")
        print(f"Correct term hits: {summary['correct_term_hits']}")
        print(f"Wrong term hits: {summary['wrong_term_hits']}")
        print(f"TCR: {summary['term_consistency_rate']}%")
        print(
            "Error types: "
            f"missing={summary['error_missing']}, "
            f"wrong_translation={summary['error_wrong_translation']}, "
            f"partial_match={summary['error_partial_match']}, "
            f"ambiguous={summary['error_ambiguous']}"
        )
        print(f"High priority TCR: {summary['high_priority_tcr']}%")

    save_excel_report(
        summary_rows=summary_rows,
        detail_rows=detail_rows,
        error_rows=error_rows,
        output_path=output_path,
    )

    print("=" * 80)
    print(f"Report saved to: {output_path}")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
