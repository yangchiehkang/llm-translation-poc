#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Run XCOMET-XXL QE scoring for qwen-max term-prompt translations.

This launcher does more than calling score_qwen_max_qe.py:

1. Scan all JSONL files under:
       data/mt/qwen-max-term/

2. Detect failed translation rows:
       - missing mt_text
       - empty mt_text
       - mt_error == "translation_failed"

3. Build a clean scoring input directory:
       data/mt/qwen-max-term-clean/

   Failed rows are excluded because XCOMET cannot score empty translations.

4. Save failed rows report:
       data/report/xcomet-xxl-qe/term-prompt/failed_rows/qwen_max_term_prompt_failed_rows.jsonl
       data/report/xcomet-xxl-qe/term-prompt/failed_rows/qwen_max_term_prompt_failed_rows.xlsx

5. Run XCOMET-XXL QE scoring with visible progress.

6. Post-process the output Excel and add term-prompt metadata columns:
       - term_injection
       - has_term_match
       - matched_term_count
       - matched_term_pairs
       - term_table
       - original_file
       - original_line_no
       - clean_line_no
       - excluded_from_scoring

Final output:
       data/report/xcomet-xxl-qe/term-prompt/qwen_max_term_prompt_xcomet_xxl_qe.xlsx
"""

from __future__ import annotations

import json
import os
import re
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd


MT_KEY = "mt_text"


def project_root() -> Path:
    """
    Resolve project root from this file location.

    Current file:
        scripts/evaluation/run_xcomet_xxl_score_term_prompt.py

    Project root:
        ../../
    """
    return Path(__file__).resolve().parents[2]


def set_env() -> None:
    """
    Set Hugging Face / COMET cache paths to /data.

    This avoids downloading or caching large files under /home.
    Also makes Python output unbuffered so nohup logs show progress earlier.
    """
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HOME", "/data/yinzs/models/huggingface")
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", "/data/yinzs/models/huggingface/hub")
    os.environ.setdefault("TRANSFORMERS_CACHE", "/data/yinzs/models/huggingface/transformers")
    os.environ.setdefault("TORCH_HOME", "/data/yinzs/models/torch")
    os.environ.setdefault("COMET_CACHE", "/data/yinzs/models/comet")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")


def extract_lang_from_filename(path: Path) -> str:
    """
    Extract language code from names like:
        mt_de._qwen-max.jsonl
        mt_vi._qwen-max.jsonl
        mt_en_qwen-max.jsonl

    Returns:
        de / vi / en ...
    """
    name = path.name

    m = re.match(r"^mt_([A-Za-z0-9-]+)\.?", name)
    if m:
        return m.group(1).strip().lower()

    return path.stem


def is_missing_mt(obj: dict[str, Any]) -> bool:
    """
    Decide whether a row should be excluded from XCOMET scoring.
    """
    mt = obj.get(MT_KEY)

    if mt is None:
        return True

    if str(mt).strip() == "":
        return True

    return False


def term_pairs_from_obj(obj: dict[str, Any]) -> str:
    """
    Convert matched_terms into a compact readable string:
        source => target; source2 => target2
    """
    matched_terms = obj.get("matched_terms")

    if not isinstance(matched_terms, list):
        return ""

    pairs: list[str] = []

    for item in matched_terms:
        if not isinstance(item, dict):
            continue

        src = str(item.get("source_term", "")).strip()
        tgt = str(item.get("target_term", "")).strip()

        if src or tgt:
            pairs.append(f"{src} => {tgt}")

    return "; ".join(pairs)


def build_clean_inputs(
    src_dir: Path,
    clean_dir: Path,
    failed_jsonl: Path,
    failed_xlsx: Path,
    glob_pattern: str = "*.jsonl",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Build clean JSONL files for scoring.

    Returns:
        valid_rows_meta, failed_rows
    """
    if clean_dir.exists():
        shutil.rmtree(clean_dir)

    clean_dir.mkdir(parents=True, exist_ok=True)
    failed_jsonl.parent.mkdir(parents=True, exist_ok=True)

    valid_rows_meta: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []

    files = sorted(src_dir.glob(glob_pattern))

    print("=" * 80, flush=True)
    print("Preflight check: scanning term-prompt translation files", flush=True)
    print("=" * 80, flush=True)
    print(f"Source MT dir : {src_dir}", flush=True)
    print(f"Clean MT dir  : {clean_dir}", flush=True)
    print(f"Matched files : {len(files)}", flush=True)

    for p in files:
        print(f"  - {p.name}", flush=True)

    print("=" * 80, flush=True)

    total_input = 0
    total_kept = 0
    total_failed = 0

    for p in files:
        lang = extract_lang_from_filename(p)
        out = clean_dir / p.name

        file_total = 0
        file_kept = 0
        file_failed = 0

        with p.open("r", encoding="utf-8") as fi, out.open("w", encoding="utf-8") as fo:
            for original_line_no, line in enumerate(fi, start=1):
                file_total += 1
                total_input += 1

                try:
                    obj = json.loads(line)
                except Exception as e:
                    failed = {
                        "_file": p.name,
                        "_lang": lang,
                        "_original_line_no": original_line_no,
                        "_reason": f"json_decode_error: {e}",
                        "_raw_line": line,
                    }
                    failed_rows.append(failed)
                    file_failed += 1
                    total_failed += 1
                    continue

                missing_mt = is_missing_mt(obj)

                if missing_mt:
                    failed = dict(obj)
                    failed["_file"] = p.name
                    failed["_lang"] = lang
                    failed["_original_line_no"] = original_line_no
                    failed["_reason"] = "missing_or_empty_mt_text"
                    failed_rows.append(failed)

                    file_failed += 1
                    total_failed += 1
                    continue

                file_kept += 1
                total_kept += 1

                obj["_original_file"] = p.name
                obj["_original_line_no"] = original_line_no
                obj["_clean_line_no"] = file_kept
                obj["_excluded_from_scoring"] = False

                fo.write(json.dumps(obj, ensure_ascii=False) + "\n")

                valid_rows_meta.append(
                    {
                        "lang": obj.get("lang") or lang,
                        "seg_id": obj.get("seg_id", ""),
                        "src_file": obj.get("src_file", ""),
                        "page_no": obj.get("page_no", ""),
                        "text": obj.get("text", ""),
                        "mt_text": obj.get("mt_text", ""),
                        "term_injection": bool(obj.get("term_injection", False)),
                        "has_term_match": int(obj.get("matched_term_count", 0) or 0) > 0,
                        "matched_term_count": int(obj.get("matched_term_count", 0) or 0),
                        "matched_term_pairs": term_pairs_from_obj(obj),
                        "term_table": obj.get("term_table", ""),
                        "original_file": p.name,
                        "original_line_no": original_line_no,
                        "clean_line_no": file_kept,
                        "excluded_from_scoring": False,
                    }
                )

        print(
            f"{p.name}: total={file_total}, kept={file_kept}, failed={file_failed}",
            flush=True,
        )

    with failed_jsonl.open("w", encoding="utf-8") as fo:
        for row in failed_rows:
            fo.write(json.dumps(row, ensure_ascii=False) + "\n")

    if failed_rows:
        pd.DataFrame(failed_rows).to_excel(failed_xlsx, index=False)
    else:
        pd.DataFrame(
            columns=[
                "_file",
                "_lang",
                "_original_line_no",
                "_reason",
            ]
        ).to_excel(failed_xlsx, index=False)

    print("=" * 80, flush=True)
    print("Preflight summary", flush=True)
    print("=" * 80, flush=True)
    print(f"Total input rows : {total_input}", flush=True)
    print(f"Valid rows       : {total_kept}", flush=True)
    print(f"Failed rows      : {total_failed}", flush=True)
    print(f"Failed JSONL     : {failed_jsonl}", flush=True)
    print(f"Failed XLSX      : {failed_xlsx}", flush=True)
    print("=" * 80, flush=True)

    return valid_rows_meta, failed_rows


def save_metadata(valid_rows_meta: list[dict[str, Any]], meta_xlsx: Path, meta_jsonl: Path) -> None:
    """
    Save valid-row metadata for traceability and final Excel post-processing.
    """
    meta_xlsx.parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(valid_rows_meta)
    df.to_excel(meta_xlsx, index=False)

    with meta_jsonl.open("w", encoding="utf-8") as fo:
        for row in valid_rows_meta:
            fo.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Valid metadata XLSX : {meta_xlsx}", flush=True)
    print(f"Valid metadata JSONL : {meta_jsonl}", flush=True)


def print_term_match_summary(valid_rows_meta: list[dict[str, Any]], failed_rows: list[dict[str, Any]]) -> None:
    """
    Print term match summary by language.
    """
    df = pd.DataFrame(valid_rows_meta)

    print("=" * 80, flush=True)
    print("Term match summary on valid scoring rows", flush=True)
    print("=" * 80, flush=True)

    if df.empty:
        print("[WARN] no valid rows found.", flush=True)
        return

    rows = []

    for lang, g in df.groupby("lang", dropna=False):
        total = len(g)
        matched = int(g["has_term_match"].sum())
        unmatched = total - matched
        ratio = matched / total if total else 0.0

        rows.append(
            {
                "lang": lang,
                "valid_rows": total,
                "term_matched_rows": matched,
                "non_term_rows": unmatched,
                "term_match_ratio": ratio,
            }
        )

    summary = pd.DataFrame(rows).sort_values("lang")

    print(summary.to_string(index=False), flush=True)

    if failed_rows:
        failed_df = pd.DataFrame(failed_rows)
        if "_lang" in failed_df.columns:
            print("=" * 80, flush=True)
            print("Failed translation rows by language", flush=True)
            print("=" * 80, flush=True)
            print(failed_df.groupby("_lang").size().to_string(), flush=True)

    print("=" * 80, flush=True)


def run_scoring(
    root: Path,
    score_script: Path,
    mt_dir: Path,
    out_xlsx: Path,
    xcomet_ckpt: Path,
    device: str,
    batch: str,
    glob_pattern: str,
) -> int:
    """
    Run score_qwen_max_qe.py with real-time visible logs.
    """
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-u",
        str(score_script),
        "--mt_dir",
        str(mt_dir),
        "--out_xlsx",
        str(out_xlsx),
        "--xcomet_ckpt",
        str(xcomet_ckpt),
        "--device",
        device,
        "--batch",
        batch,
        "--glob",
        glob_pattern,
    ]

    print("=" * 80, flush=True)
    print("Running XCOMET-XXL QE scoring", flush=True)
    print("=" * 80, flush=True)
    print("Running command:", flush=True)
    print(" ".join(cmd), flush=True)
    print("=" * 80, flush=True)

    result = subprocess.run(
        cmd,
        cwd=str(root),
        env=os.environ.copy(),
    )

    return result.returncode


def load_score_excel(out_xlsx: Path) -> dict[str, pd.DataFrame]:
    """
    Load all sheets from output Excel.
    """
    return pd.read_excel(out_xlsx, sheet_name=None)


def find_detail_sheet(sheets: dict[str, pd.DataFrame]) -> str:
    """
    Heuristically find the sheet containing sentence-level rows.

    If score_qwen_max_qe.py writes only one sheet, use that.
    Otherwise prefer sheets with row-level columns such as seg_id/text/mt_text.
    """
    if len(sheets) == 1:
        return next(iter(sheets.keys()))

    candidates = []

    for name, df in sheets.items():
        cols = set(map(str, df.columns))

        score = 0
        for c in ["seg_id", "text", "mt_text", "src", "mt", "score", "xcomet_score"]:
            if c in cols:
                score += 1

        candidates.append((score, len(df), name))

    candidates.sort(reverse=True)
    return candidates[0][2]


def add_term_annotations_to_excel(
    out_xlsx: Path,
    annotated_xlsx: Path,
    valid_rows_meta: list[dict[str, Any]],
) -> None:
    """
    Add term match metadata into the scoring Excel.

    Strategy:
    1. Try to merge by seg_id.
    2. If seg_id does not exist in score sheet, fall back to row order.
    """
    if not out_xlsx.is_file():
        print(f"[WARN] score output not found, skip annotation: {out_xlsx}", flush=True)
        return

    meta = pd.DataFrame(valid_rows_meta)

    if meta.empty:
        print("[WARN] empty metadata, skip annotation.", flush=True)
        return

    sheets = load_score_excel(out_xlsx)
    detail_sheet = find_detail_sheet(sheets)

    print("=" * 80, flush=True)
    print("Post-processing score Excel: adding term annotations", flush=True)
    print("=" * 80, flush=True)
    print(f"Input Excel      : {out_xlsx}", flush=True)
    print(f"Annotated Excel  : {annotated_xlsx}", flush=True)
    print(f"Detail sheet     : {detail_sheet}", flush=True)

    annotation_cols = [
        "term_injection",
        "has_term_match",
        "matched_term_count",
        "matched_term_pairs",
        "term_table",
        "original_file",
        "original_line_no",
        "clean_line_no",
        "excluded_from_scoring",
    ]

    for sheet_name, df in sheets.items():
        if sheet_name != detail_sheet:
            continue

        df = df.copy()

        if "seg_id" in df.columns and "seg_id" in meta.columns:
            meta_small = meta[["seg_id"] + annotation_cols].copy()
            meta_small = meta_small.drop_duplicates(subset=["seg_id"], keep="first")

            df = df.merge(meta_small, on="seg_id", how="left")

            print("Annotation method: merge by seg_id", flush=True)

        else:
            print("Annotation method: fallback by row order", flush=True)

            n = min(len(df), len(meta))

            for col in annotation_cols:
                df[col] = None
                df.loc[: n - 1, col] = meta[col].iloc[:n].to_list()

            if len(df) != len(meta):
                print(
                    f"[WARN] row count mismatch: score_rows={len(df)}, meta_rows={len(meta)}",
                    flush=True,
                )

        # Add a more human-readable label column for comparison.
        if "has_term_match" in df.columns:
            df["term_match_label"] = df["has_term_match"].map(
                {
                    True: "term-matched",
                    False: "no-term-match",
                    1: "term-matched",
                    0: "no-term-match",
                }
            )

        sheets[sheet_name] = df

    # Add summary sheets for easier comparison.
    detail_df = sheets[detail_sheet]

    if "has_term_match" in detail_df.columns:
        score_cols = [
            c
            for c in detail_df.columns
            if str(c).lower()
            in {
                "score",
                "xcomet_score",
                "comet_score",
                "mqm_score",
                "system_score",
            }
        ]

        if score_cols:
            score_col = score_cols[0]

            try:
                summary_by_term = (
                    detail_df.groupby("has_term_match", dropna=False)[score_col]
                    .agg(["count", "mean", "median", "std", "min", "max"])
                    .reset_index()
                )
                sheets["summary_by_term_match"] = summary_by_term
            except Exception as e:
                print(f"[WARN] failed to build summary_by_term_match: {e}", flush=True)

            if "lang" in detail_df.columns:
                try:
                    summary_by_lang_term = (
                        detail_df.groupby(["lang", "has_term_match"], dropna=False)[score_col]
                        .agg(["count", "mean", "median", "std", "min", "max"])
                        .reset_index()
                    )
                    sheets["summary_by_lang_term"] = summary_by_lang_term
                except Exception as e:
                    print(f"[WARN] failed to build summary_by_lang_term: {e}", flush=True)

    annotated_xlsx.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(annotated_xlsx, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_name = str(sheet_name)[:31]
            df.to_excel(writer, sheet_name=safe_name, index=False)

    # Also overwrite the original output so downstream scripts can use the same path.
    shutil.copy2(annotated_xlsx, out_xlsx)

    print("Annotation finished.", flush=True)
    print(f"Final report saved to: {out_xlsx}", flush=True)
    print("=" * 80, flush=True)


def main() -> int:
    set_env()

    root = project_root()

    score_script = root / "scripts" / "evaluation" / "score_qwen_max_qe.py"

    # Original term-prompt outputs, including newly added vi if present.
    raw_mt_dir = root / "data" / "mt" / "qwen-max-term"

    # Clean scoring inputs generated by this launcher.
    clean_mt_dir = root / "data" / "mt" / "qwen-max-term-clean"

    # Final reports.
    report_dir = root / "data" / "report" / "xcomet-xxl-qe" / "term-prompt"
    out_xlsx = report_dir / "qwen_max_term_prompt_xcomet_xxl_qe.xlsx"
    annotated_xlsx = report_dir / "qwen_max_term_prompt_xcomet_xxl_qe.annotated.xlsx"

    # Failure and metadata reports.
    failed_dir = report_dir / "failed_rows"
    failed_jsonl = failed_dir / "qwen_max_term_prompt_failed_rows.jsonl"
    failed_xlsx = failed_dir / "qwen_max_term_prompt_failed_rows.xlsx"

    meta_dir = report_dir / "metadata"
    meta_xlsx = meta_dir / "qwen_max_term_prompt_valid_rows_metadata.xlsx"
    meta_jsonl = meta_dir / "qwen_max_term_prompt_valid_rows_metadata.jsonl"

    xcomet_ckpt = Path("/data/yinzs/models/xcomet-xxl/checkpoints/model.ckpt")

    device = "npu"
    batch = "1"
    glob_pattern = "*.jsonl"

    print("=" * 80, flush=True)
    print("XCOMET-XXL QE Scoring - Term Prompt Pipeline", flush=True)
    print("=" * 80, flush=True)
    print(f"Project root      : {root}", flush=True)
    print(f"Score script      : {score_script}", flush=True)
    print(f"Raw MT dir        : {raw_mt_dir}", flush=True)
    print(f"Clean MT dir      : {clean_mt_dir}", flush=True)
    print(f"Output xlsx       : {out_xlsx}", flush=True)
    print(f"Annotated xlsx    : {annotated_xlsx}", flush=True)
    print(f"XCOMET ckpt       : {xcomet_ckpt}", flush=True)
    print(f"Device            : {device}", flush=True)
    print(f"Batch             : {batch}", flush=True)
    print(f"Glob              : {glob_pattern}", flush=True)
    print("=" * 80, flush=True)

    if not score_script.is_file():
        print(f"[ERROR] score script not found: {score_script}", file=sys.stderr, flush=True)
        return 1

    if not raw_mt_dir.is_dir():
        print(f"[ERROR] raw mt_dir not found: {raw_mt_dir}", file=sys.stderr, flush=True)
        return 1

    if not xcomet_ckpt.is_file():
        print(f"[ERROR] XCOMET-XXL checkpoint not found: {xcomet_ckpt}", file=sys.stderr, flush=True)
        print("Please check whether the model has been downloaded successfully.", file=sys.stderr, flush=True)
        return 1

    raw_files = sorted(raw_mt_dir.glob(glob_pattern))
    if not raw_files:
        print(f"[ERROR] no jsonl files found in raw mt_dir: {raw_mt_dir}", file=sys.stderr, flush=True)
        return 1

    report_dir.mkdir(parents=True, exist_ok=True)

    valid_rows_meta, failed_rows = build_clean_inputs(
        src_dir=raw_mt_dir,
        clean_dir=clean_mt_dir,
        failed_jsonl=failed_jsonl,
        failed_xlsx=failed_xlsx,
        glob_pattern=glob_pattern,
    )

    save_metadata(
        valid_rows_meta=valid_rows_meta,
        meta_xlsx=meta_xlsx,
        meta_jsonl=meta_jsonl,
    )

    print_term_match_summary(valid_rows_meta, failed_rows)

    if not valid_rows_meta:
        print("[ERROR] no valid rows to score.", file=sys.stderr, flush=True)
        return 1

    result_code = run_scoring(
        root=root,
        score_script=score_script,
        mt_dir=clean_mt_dir,
        out_xlsx=out_xlsx,
        xcomet_ckpt=xcomet_ckpt,
        device=device,
        batch=batch,
        glob_pattern=glob_pattern,
    )

    if result_code != 0:
        print("=" * 80, flush=True)
        print(f"[ERROR] term-prompt scoring failed with return code: {result_code}", file=sys.stderr, flush=True)
        print("=" * 80, flush=True)
        return result_code

    add_term_annotations_to_excel(
        out_xlsx=out_xlsx,
        annotated_xlsx=annotated_xlsx,
        valid_rows_meta=valid_rows_meta,
    )

    print("=" * 80, flush=True)
    print("Term-prompt scoring pipeline finished successfully.", flush=True)
    print("=" * 80, flush=True)
    print(f"Final report          : {out_xlsx}", flush=True)
    print(f"Annotated backup      : {annotated_xlsx}", flush=True)
    print(f"Failed rows JSONL     : {failed_jsonl}", flush=True)
    print(f"Failed rows XLSX      : {failed_xlsx}", flush=True)
    print(f"Valid metadata XLSX   : {meta_xlsx}", flush=True)
    print("=" * 80, flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
