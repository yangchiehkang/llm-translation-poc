import argparse
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = [
    "term_id",
    "source_lang",
    "target_lang",
    "source_term",
    "target_term",
    "domain",
    "priority",
    "alias",
    "note",
    "status",
]

VALID_PRIORITY = {"high", "medium", "low"}
VALID_STATUS = {"active", "review", "deprecated"}

REQUIRED_NON_EMPTY_COLUMNS = [
    "term_id",
    "source_lang",
    "target_lang",
    "source_term",
    "target_term",
    "domain",
    "priority",
    "status",
]


def normalize_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def build_validation_report(df):
    report = {}

    report["summary"] = pd.DataFrame(
        [
            {"metric": "total_rows", "value": len(df)},
            {"metric": "total_columns", "value": len(df.columns)},
            {"metric": "unique_source_lang", "value": df["source_lang"].nunique() if "source_lang" in df.columns else 0},
            {"metric": "unique_domains", "value": df["domain"].nunique() if "domain" in df.columns else 0},
        ]
    )

    missing_columns = [
        col for col in REQUIRED_COLUMNS
        if col not in df.columns
    ]

    extra_columns = [
        col for col in df.columns
        if col not in REQUIRED_COLUMNS
    ]

    report["columns_check"] = pd.DataFrame(
        [
            {"check": "missing_columns", "value": ", ".join(missing_columns)},
            {"check": "extra_columns", "value": ", ".join(extra_columns)},
            {"check": "actual_columns", "value": ", ".join(df.columns)},
        ]
    )

    empty_records = []
    for col in REQUIRED_NON_EMPTY_COLUMNS:
        if col not in df.columns:
            continue

        mask = df[col].isna() | (df[col].astype(str).str.strip() == "")
        for idx, row in df[mask].iterrows():
            empty_records.append({
                "row_index": idx + 2,
                "column": col,
                "term_id": row.get("term_id", ""),
                "source_lang": row.get("source_lang", ""),
                "source_term": row.get("source_term", ""),
                "target_term": row.get("target_term", ""),
            })

    report["empty_required_fields"] = pd.DataFrame(empty_records)

    invalid_priority = pd.DataFrame()
    if "priority" in df.columns:
        invalid_priority = df[
            ~df["priority"].fillna("").astype(str).str.strip().isin(VALID_PRIORITY)
        ].copy()

    report["invalid_priority"] = invalid_priority

    invalid_status = pd.DataFrame()
    if "status" in df.columns:
        invalid_status = df[
            ~df["status"].fillna("").astype(str).str.strip().isin(VALID_STATUS)
        ].copy()

    report["invalid_status"] = invalid_status

    duplicate_keys = ["source_lang", "target_lang", "source_term"]
    if all(col in df.columns for col in duplicate_keys):
        dup = df[
            df.duplicated(duplicate_keys, keep=False)
        ].copy()
        dup = dup.sort_values(duplicate_keys)
    else:
        dup = pd.DataFrame()

    report["duplicates"] = dup

    if "source_lang" in df.columns:
        report["count_by_source_lang"] = (
            df["source_lang"]
            .fillna("")
            .astype(str)
            .str.strip()
            .value_counts()
            .rename_axis("source_lang")
            .reset_index(name="count")
        )
    else:
        report["count_by_source_lang"] = pd.DataFrame()

    if "priority" in df.columns:
        report["count_by_priority"] = (
            df["priority"]
            .fillna("")
            .astype(str)
            .str.strip()
            .value_counts()
            .rename_axis("priority")
            .reset_index(name="count")
        )
    else:
        report["count_by_priority"] = pd.DataFrame()

    if "status" in df.columns:
        report["count_by_status"] = (
            df["status"]
            .fillna("")
            .astype(str)
            .str.strip()
            .value_counts()
            .rename_axis("status")
            .reset_index(name="count")
        )
    else:
        report["count_by_status"] = pd.DataFrame()

    if "domain" in df.columns:
        report["count_by_domain"] = (
            df["domain"]
            .fillna("")
            .astype(str)
            .str.strip()
            .value_counts()
            .rename_axis("domain")
            .reset_index(name="count")
        )
    else:
        report["count_by_domain"] = pd.DataFrame()

    if "status" in df.columns:
        review_deprecated = df[
            df["status"].fillna("").astype(str).str.strip().isin(["review", "deprecated"])
        ].copy()
    else:
        review_deprecated = pd.DataFrame()

    report["review_deprecated"] = review_deprecated

    broad_terms = {
        "system",
        "part",
        "device",
        "test",
        "standard",
        "shall",
        "may",
        "requirement",
        "系统",
        "部件",
        "零件",
        "装置",
        "试验",
        "测试",
        "标准",
        "应",
        "可",
        "要求",
    }

    if "source_term" in df.columns:
        broad_mask = df["source_term"].fillna("").astype(str).str.strip().str.lower().isin(broad_terms)
        broad_df = df[broad_mask].copy()
    else:
        broad_df = pd.DataFrame()

    report["possible_broad_terms"] = broad_df

    return report


def print_terminal_summary(report):
    print("\n=== Termbase V0.2 Validation Summary ===")

    print("\n[Summary]")
    print(report["summary"].to_string(index=False))

    print("\n[Columns Check]")
    print(report["columns_check"].to_string(index=False))

    print("\n[Count by source_lang]")
    print(report["count_by_source_lang"].to_string(index=False))

    print("\n[Count by priority]")
    print(report["count_by_priority"].to_string(index=False))

    print("\n[Count by status]")
    print(report["count_by_status"].to_string(index=False))

    print("\n[Issues]")
    print("empty_required_fields:", len(report["empty_required_fields"]))
    print("invalid_priority:", len(report["invalid_priority"]))
    print("invalid_status:", len(report["invalid_status"]))
    print("duplicates:", len(report["duplicates"]))
    print("review_deprecated:", len(report["review_deprecated"]))
    print("possible_broad_terms:", len(report["possible_broad_terms"]))


def write_excel_report(report, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, data in report.items():
            safe_sheet_name = sheet_name[:31]

            if data is None or len(data) == 0:
                data = pd.DataFrame({"message": ["no records"]})

            data.to_excel(writer, sheet_name=safe_sheet_name, index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        required=True,
        help="Input termbase CSV path",
    )
    parser.add_argument(
        "--output",
        default="data/report/termbase/termbase_v0.2_validation.xlsx",
        help="Output validation report Excel path",
    )
    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        raise FileNotFoundError(input_path)

    df = pd.read_csv(input_path, encoding="utf-8-sig", dtype=str)
    df = df.fillna("")

    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()

    report = build_validation_report(df)

    print_terminal_summary(report)
    write_excel_report(report, args.output)

    print("\nValidation report written to:")
    print(args.output)


if __name__ == "__main__":
    main()
