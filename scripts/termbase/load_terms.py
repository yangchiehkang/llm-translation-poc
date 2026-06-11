import argparse
import csv
from pathlib import Path
from typing import Dict, List


REQUIRED_COLUMNS = [
    "term_id",
    "source_lang",
    "source_term",
    "target_lang",
    "target_term",
    "domain",
    "priority",
    "case_sensitive",
    "match_type",
]


def normalize_bool(value: str) -> bool:
    if value is None:
        return False

    value = str(value).strip().lower()

    if value in {"true", "1", "yes", "y"}:
        return True

    if value in {"false", "0", "no", "n", ""}:
        return False

    return False


def load_terms(
    termbase_path: str,
    source_lang: str = None,
    target_lang: str = "zh",
) -> List[Dict]:
    path = Path(termbase_path)

    if not path.exists():
        raise FileNotFoundError(f"Termbase file not found: {path}")

    terms = []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise ValueError(f"Empty termbase file: {path}")

        missing_columns = [
            col for col in REQUIRED_COLUMNS if col not in reader.fieldnames
        ]

        if missing_columns:
            raise ValueError(
                f"Missing required columns in termbase: {missing_columns}. "
                f"Current columns: {reader.fieldnames}"
            )

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

            term = {
                "term_id": term_id,
                "source_lang": src_lang,
                "source_term": src_term,
                "target_lang": tgt_lang,
                "target_term": tgt_term,
                "domain": str(row.get("domain", "")).strip(),
                "priority": str(row.get("priority", "")).strip(),
                "case_sensitive": normalize_bool(row.get("case_sensitive", "")),
                "match_type": str(row.get("match_type", "exact")).strip() or "exact",
                "note": str(row.get("note", "")).strip(),
            }

            terms.append(term)

    return terms


def print_terms_summary(terms: List[Dict], source_lang: str = None) -> None:
    print("=" * 80)
    print("Termbase Load Summary")
    print("=" * 80)
    print(f"Source language filter: {source_lang or 'ALL'}")
    print(f"Loaded terms: {len(terms)}")

    lang_count = {}
    domain_count = {}

    for term in terms:
        lang = term["source_lang"]
        domain = term.get("domain", "")

        lang_count[lang] = lang_count.get(lang, 0) + 1
        domain_count[domain] = domain_count.get(domain, 0) + 1

    print("\nBy language:")
    for lang, count in sorted(lang_count.items()):
        print(f"  {lang}: {count}")

    print("\nBy domain:")
    for domain, count in sorted(domain_count.items()):
        print(f"  {domain or 'UNKNOWN'}: {count}")

    print("\nPreview:")
    for term in terms[:10]:
        print(
            f"  [{term['term_id']}] "
            f"{term['source_lang']}:{term['source_term']} -> "
            f"{term['target_lang']}:{term['target_term']} "
            f"({term['domain']}, {term['priority']})"
        )

    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Load and validate automotive regulation termbase."
    )

    parser.add_argument(
        "--termbase",
        default="termbase/auto_regulation_terms.csv",
        help="Path to termbase CSV file.",
    )

    parser.add_argument(
        "--lang",
        default=None,
        help="Source language filter, e.g. en, ru, de, fr, ar.",
    )

    parser.add_argument(
        "--target-lang",
        default="zh",
        help="Target language filter. Default: zh.",
    )

    args = parser.parse_args()

    terms = load_terms(
        termbase_path=args.termbase,
        source_lang=args.lang,
        target_lang=args.target_lang,
    )

    print_terms_summary(terms, source_lang=args.lang)


if __name__ == "__main__":
    main()
