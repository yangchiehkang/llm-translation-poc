import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.termbase.load_terms import load_terms


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


def write_jsonl(records: List[Dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def term_exists_in_text(source_text: str, term: Dict) -> bool:
    source_term = str(term.get("source_term", "") or "")
    source_lang = str(term.get("source_lang", "") or "")
    case_sensitive = bool(term.get("case_sensitive", False))

    if not source_text or not source_term:
        return False

    if case_sensitive:
        text_for_match = source_text
        term_for_match = source_term
    else:
        text_for_match = source_text.lower()
        term_for_match = source_term.lower()

    alphabetic_langs = {
        "en", "es", "de", "fr", "pt", "it", "nl", "no", "sv", "vi", "id", "ms"
    }

    if source_lang in alphabetic_langs:
        escaped = re.escape(term_for_match)
        pattern = rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"
        return re.search(pattern, text_for_match) is not None

    return term_for_match in text_for_match


def match_terms_for_record(record: Dict, terms: List[Dict], lang: str, index: int) -> Dict:
    source_text = str(record.get("text", "") or "")
    record_id = str(record.get("seg_id", "") or f"{lang}_{index:06d}")
    src_lang = str(record.get("lang", "") or lang)

    matched_terms = []

    for term in terms:
        if term_exists_in_text(source_text, term):
            matched_terms.append(
                {
                    "term_id": term["term_id"],
                    "source_term": term["source_term"],
                    "target_term": term["target_term"],
                    "domain": term.get("domain", ""),
                    "priority": term.get("priority", ""),
                    "match_type": term.get("match_type", "exact"),
                }
            )

    output_record = {
        "id": record_id,
        "src_lang": src_lang,
        "source": source_text,
        "matched_terms": matched_terms,
    }

    if "src_file" in record:
        output_record["source_file"] = record.get("src_file")

    if "page_no" in record:
        output_record["page"] = record.get("page_no")

    return output_record


def summarize_matches(records: List[Dict]) -> Dict:
    total_records = len(records)
    records_with_source = 0
    records_with_terms = 0
    total_term_hits = 0

    domain_count = {}
    priority_count = {}

    for record in records:
        source = record.get("source", "")
        matched_terms = record.get("matched_terms", [])

        if source:
            records_with_source += 1

        if matched_terms:
            records_with_terms += 1

        total_term_hits += len(matched_terms)

        for term in matched_terms:
            domain = term.get("domain", "") or "UNKNOWN"
            priority = term.get("priority", "") or "UNKNOWN"

            domain_count[domain] = domain_count.get(domain, 0) + 1
            priority_count[priority] = priority_count.get(priority, 0) + 1

    return {
        "total_records": total_records,
        "records_with_source": records_with_source,
        "records_with_terms": records_with_terms,
        "total_term_hits": total_term_hits,
        "domain_count": domain_count,
        "priority_count": priority_count,
    }


def print_summary(lang: str, input_path: Path, output_path: Path, summary: Dict) -> None:
    print("=" * 80)
    print("Term Matching Summary")
    print("=" * 80)
    print(f"Language: {lang}")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Total records: {summary['total_records']}")
    print(f"Records with source text: {summary['records_with_source']}")
    print(f"Records with matched terms: {summary['records_with_terms']}")
    print(f"Total term hits: {summary['total_term_hits']}")

    if summary["total_records"] > 0:
        source_coverage = summary["records_with_source"] / summary["total_records"] * 100
        term_coverage = summary["records_with_terms"] / summary["total_records"] * 100
        print(f"Source coverage: {source_coverage:.2f}%")
        print(f"Term record coverage: {term_coverage:.2f}%")

    print("\nBy domain:")
    for domain, count in sorted(summary["domain_count"].items()):
        print(f"  {domain}: {count}")

    print("\nBy priority:")
    for priority, count in sorted(summary["priority_count"].items()):
        print(f"  {priority}: {count}")

    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Match source terms in evaluation JSONL files."
    )

    parser.add_argument(
        "--lang",
        required=True,
        help="Source language code, e.g. en, ru, de, fr, ar.",
    )

    parser.add_argument(
        "--input",
        default=None,
        help="Input eval JSONL path. Default: data/eval/{lang}.jsonl",
    )

    parser.add_argument(
        "--termbase",
        default="termbase/auto_regulation_terms.csv",
        help="Path to termbase CSV.",
    )

    parser.add_argument(
        "--output",
        default=None,
        help="Output JSONL path. Default: data/report/term-consistency/{lang}_term_matches.jsonl",
    )

    parser.add_argument(
        "--target-lang",
        default="zh",
        help="Target language. Default: zh.",
    )

    args = parser.parse_args()

    lang = args.lang

    input_path = Path(args.input) if args.input else Path(f"data/eval/{lang}.jsonl")
    output_path = (
        Path(args.output)
        if args.output
        else Path(f"data/report/term-consistency/{lang}_term_matches.jsonl")
    )

    terms = load_terms(
        termbase_path=args.termbase,
        source_lang=lang,
        target_lang=args.target_lang,
    )

    records = read_jsonl(input_path)

    matched_records = [
        match_terms_for_record(record, terms, lang, index=i)
        for i, record in enumerate(records, start=1)
    ]

    write_jsonl(matched_records, output_path)

    summary = summarize_matches(matched_records)

    print_summary(
        lang=lang,
        input_path=input_path,
        output_path=output_path,
        summary=summary,
    )


if __name__ == "__main__":
    main()
