import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.termbase.load_terms import load_terms


LANGS = [
    "ar", "de", "en", "es", "fr",
    "id", "it", "ms", "nl", "no",
    "pt", "ru", "sv", "th", "vi",
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

    total_term_hits = 0
    correct_term_hits = 0
    wrong_term_hits = 0
    records_with_prediction = 0

    for index, record in enumerate(records, start=1):
        record_id = get_record_id(record, lang, index)

        source = get_value(record, SOURCE_FIELD_CANDIDATES, "")
        prediction = get_value(record, PREDICTION_FIELD_CANDIDATES, "")

        if prediction:
            records_with_prediction += 1

        src_lang = str(record.get("src_lang", record.get("lang", lang)) or lang)

        for term in terms:
            source_hit = term_exists_in_text(
                text=source,
                term=term,
                use_source_lang=True,
            )

            if not source_hit:
                continue

            total_term_hits += 1

            target_hit = term_exists_in_text(
                text=prediction,
                term=term,
                use_source_lang=False,
            )

            if target_hit:
                correct_term_hits += 1
                status = "correct"
                error_type = ""
            else:
                wrong_term_hits += 1
                status = "wrong"
                error_type = "target_term_missing"

            row = {
                "id": record_id,
                "src_lang": src_lang,
                "source_term": term.get("source_term", ""),
                "expected_target_term": term.get("target_term", ""),
                "domain": term.get("domain", ""),
                "priority": term.get("priority", ""),
                "source": source,
                "prediction": prediction,
                "status": status,
                "error_type": error_type,
            }

            detail_rows.append(row)

            if status == "wrong":
                error_rows.append(row)

    rate = (
        correct_term_hits / total_term_hits * 100
        if total_term_hits > 0
        else 0.0
    )

    summary_row = {
        "src_lang": lang,
        "mt_file": str(mt_path),
        "total_records": len(records),
        "records_with_prediction": records_with_prediction,
        "loaded_terms": len(terms),
        "total_term_hits": total_term_hits,
        "correct_term_hits": correct_term_hits,
        "wrong_term_hits": wrong_term_hits,
        "term_consistency_rate": round(rate, 2),
    }

    return {
        "summary": summary_row,
        "details": detail_rows,
        "errors": error_rows,
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

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        details_df.to_excel(writer, sheet_name="details", index=False)
        errors_df.to_excel(writer, sheet_name="errors", index=False)


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


def main():
    parser = argparse.ArgumentParser(
        description="Check term consistency between source and MT prediction."
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
        help="MT model name.",
    )

    parser.add_argument(
        "--mt-root",
        default="data/mt",
        help="MT root directory.",
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
        default="data/report/term-consistency/term_consistency_report.xlsx",
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
        print(f"Language: {lang}")

        if mt_path is None:
            print(f"MT file not found for language: {lang}")
            summary_rows.append(
                {
                    "src_lang": lang,
                    "mt_file": "",
                    "total_records": 0,
                    "records_with_prediction": 0,
                    "loaded_terms": 0,
                    "total_term_hits": 0,
                    "correct_term_hits": 0,
                    "wrong_term_hits": 0,
                    "term_consistency_rate": 0.0,
                    "status": "mt_file_missing",
                }
            )
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
        print(f"Term consistency rate: {summary['term_consistency_rate']}%")

    save_excel_report(
        summary_rows=summary_rows,
        detail_rows=detail_rows,
        error_rows=error_rows,
        output_path=output_path,
    )

    print("=" * 80)
    print(f"Report saved to: {output_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()
