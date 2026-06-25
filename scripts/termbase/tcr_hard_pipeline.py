"""
TCR Hard Control Pipeline — 面向甲方 TCR ≥ 90% 硬要求的术语一致性控制流程。

Pipeline 步骤：
  Step 1: Hard Required Terms 确认        → hard_required_terms.csv
  Step 2: 源文术语召回                      → term_recall.csv
  Step 3: 译后 TCR 硬校验                   → tcr_hard_check.csv + tcr_batch_summary.csv
  Step 4: 失败样本拦截队列                  → failed_sample_queue.csv
  Step 5: 定向重试样本池                    → retry_sample_pool.csv
  Step 6: 术语回流候选清单                  → term_feedback_candidates.csv
  Step 7: Pipeline 小结                    → pipeline_summary.txt

用法:
  python3 scripts/termbase/tcr_hard_pipeline.py --langs en ru es de fr th ar
  python3 scripts/termbase/tcr_hard_pipeline.py --langs all
  python3 scripts/termbase/tcr_hard_pipeline.py --step recall     # 只跑召回
  python3 scripts/termbase/tcr_hard_pipeline.py --step check      # 只跑校验
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

from scripts.utils.lang_map import RFP_LANGUAGES, get_lang_name, is_rfp_language

# ── Constants ────────────────────────────────────────────────────────────────

RFP_LANGS = ["en", "ru", "es", "de", "fr", "th", "ar"]
ALL_LANGS = RFP_LANGS + ["id", "it", "ms", "nl", "no", "pt", "sv", "vi"]

OUTPUT_DIR = PROJECT_ROOT / "data" / "report" / "tcr"

SOURCE_FIELDS = ["text", "source", "src", "src_text", "source_text", "input", "sentence", "segment"]
MT_FIELDS = ["mt_text", "prediction", "pred", "translation", "mt", "hypothesis", "output"]
ID_FIELDS = ["seg_id", "id", "sample_id", "sentence_id", "uid"]

ALPHABETIC_LANGS = {"en", "es", "de", "fr", "pt", "it", "nl", "no", "sv", "vi", "id", "ms"}

# ── Data I/O ─────────────────────────────────────────────────────────────────

def read_jsonl(path: Path) -> List[Dict]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_terms(termbase_path: Path, source_lang: str = None, target_lang: str = "zh") -> List[Dict]:
    """Load terms from V0.3 candidate CSV."""
    terms = []
    with termbase_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = str(row.get("term_id", "")).strip()
            sl = str(row.get("source_lang", "")).strip()
            st = str(row.get("source_term", "")).strip()
            tl = str(row.get("target_lang", "")).strip()
            tt = str(row.get("target_term", "")).strip()
            if not all([tid, sl, st, tl, tt]):
                continue
            if source_lang and sl != source_lang:
                continue
            if target_lang and tl != target_lang:
                continue

            alias_raw = str(row.get("alias", "") or "").strip()
            aliases = []
            if alias_raw:
                if ";" in alias_raw:
                    aliases = [a.strip() for a in alias_raw.split(";") if a.strip()]
                elif "," in alias_raw:
                    aliases = [a.strip() for a in alias_raw.split(",") if a.strip()]
                else:
                    aliases = [alias_raw]

            terms.append({
                "term_id": tid,
                "source_lang": sl,
                "source_term": st,
                "target_lang": tl,
                "target_term": tt,
                "domain": str(row.get("domain", "")).strip(),
                "priority": str(row.get("priority", "")).strip(),
                "alias": aliases,
                "tcr_scope": str(row.get("tcr_scope", "")).strip(),
                "acceptance_scope": str(row.get("acceptance_scope", "")).strip(),
            })
    return terms


def first_field(record: Dict, candidates: List[str]) -> Optional[str]:
    for f in candidates:
        if f in record:
            return f
    return None


def get_val(record: Dict, candidates: List[str], default: str = "") -> str:
    f = first_field(record, candidates)
    return str(record.get(f, "") or "") if f else default


def find_mt_files(mt_root: Path, model: str, langs: List[str]) -> Dict[str, Path]:
    """Find MT JSONL files for given languages."""
    result = {}
    model_dir = mt_root / model
    for lang in langs:
        candidates = [
            model_dir / f"mt_{lang}._{model}.jsonl",
            model_dir / f"mt_{lang}_{model}.jsonl",
            mt_root / f"mt_{lang}._{model}.jsonl",
            mt_root / f"mt_{lang}_{model}.jsonl",
        ]
        found = None
        for p in candidates:
            if p.exists():
                found = p
                break
        if not found:
            for pattern in [f"mt_{lang}*.jsonl", f"{lang}*.jsonl"]:
                matches = sorted(model_dir.glob(pattern))
                if matches:
                    found = matches[0]
                    break
        if found:
            result[lang] = found
    return result


# ── Text matching ────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    return str(text or "").lower()


def term_in_text(text: str, term_text: str, lang: str) -> bool:
    """Word-boundary-aware term matching in text."""
    if not text or not term_text:
        return False
    tm = normalize(text)
    qm = normalize(term_text)
    if lang in ALPHABETIC_LANGS:
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(qm)}(?![A-Za-z0-9_])"
        return re.search(pattern, tm) is not None
    return qm in tm


def find_partial(target: str, text: str, min_ratio: float = 0.5) -> Optional[str]:
    """Find a substantial partial match. Returns the matched substring or None."""
    target = str(target or "").strip()
    text = str(text or "")
    if not target or not text or len(target) < 2:
        return None
    min_len = max(2, int(len(target) * min_ratio))
    for length in range(len(target) - 1, min_len - 1, -1):
        for start in range(0, len(target) - length + 1):
            sub = target[start:start + length]
            if sub in text and sub != target:
                return sub
    return None


# ── Step 1: Hard Required Terms ──────────────────────────────────────────────

def step1_hard_required_terms(termbase_path: Path, langs: List[str]) -> pd.DataFrame:
    """
    确认 hard required terms 范围。
    tcr_scope=strict  → hard required
    tcr_scope=relaxed → review (不进入硬控制)
    """
    rows = []
    for lang in langs:
        terms = load_terms(termbase_path, source_lang=lang)
        for t in terms:
            rows.append({
                "source_lang": lang,
                "term_id": t["term_id"],
                "source_term": t["source_term"],
                "target_term": t["target_term"],
                "domain": t["domain"],
                "tcr_scope": t["tcr_scope"],
                "hard_required": t["tcr_scope"] == "strict",
                "aliases": "; ".join(t["alias"]),
            })

    df = pd.DataFrame(rows)
    print(f"[Step 1] Hard Required Terms: {len(df)} total, "
          f"{df['hard_required'].sum()} hard required, "
          f"{(~df['hard_required']).sum()} review")
    return df


# ── Step 2: Source Term Recall ───────────────────────────────────────────────

def step2_term_recall(
    termbase_path: Path,
    mt_files: Dict[str, Path],
) -> pd.DataFrame:
    """
    对每条 source_text 进行术语召回。
    输出每条样本命中的 hard required terms、required target terms 和 core high 命中数。
    """
    rows = []

    for lang, mt_path in sorted(mt_files.items()):
        terms = load_terms(termbase_path, source_lang=lang)
        hard_terms = [t for t in terms if t["tcr_scope"] == "strict"]
        records = read_jsonl(mt_path)

        for idx, rec in enumerate(records, start=1):
            sid = get_val(rec, ID_FIELDS, f"{lang}_{idx:06d}")
            src_text = get_val(rec, SOURCE_FIELDS, "")
            mt_text = get_val(rec, MT_FIELDS, "")

            matched_hard = []
            for t in hard_terms:
                if term_in_text(src_text, t["source_term"], lang):
                    matched_hard.append(t)

            for t in matched_hard:
                rows.append({
                    "sample_id": sid,
                    "source_lang": lang,
                    "source_text": src_text[:500],
                    "mt_text": mt_text[:500],
                    "matched_source_term": t["source_term"],
                    "required_target_term": t["target_term"],
                    "term_id": t["term_id"],
                    "domain": t["domain"],
                    "tcr_scope": t["tcr_scope"],
                    "aliases": "; ".join(t["alias"]),
                    "is_hard_required": True,
                })

    df = pd.DataFrame(rows)

    # Per-sample summary
    if not df.empty:
        per_sample = df.groupby(["sample_id", "source_lang"]).agg(
            source_text=("source_text", "first"),
            mt_text=("mt_text", "first"),
            core_high_count=("is_hard_required", "sum"),
            matched_terms=("matched_source_term", lambda x: " | ".join(x)),
            required_target_terms=("required_target_term", lambda x: " | ".join(x)),
        ).reset_index()
        per_sample.to_csv(OUTPUT_DIR / "term_recall_per_sample.csv", index=False, encoding="utf-8-sig")

    print(f"[Step 2] Term Recall: {len(df)} term hits across {df['sample_id'].nunique() if not df.empty else 0} samples")
    return df


# ── Step 3: Post-Translation TCR Hard Check ──────────────────────────────────

def classify_error(required_target: str, mt_text: str, aliases: List[str],
                   source_term: str = "", target_lang: str = "zh",
                   source_lang: str = "") -> Dict:
    """
    Classify a single term check result with fine-grained error types.

    Check order (first match wins):
      1. Exact match of required target term  → pass
      2. Exact match of alias                  → alias_only (MT used alias instead)
      3. Partial match of required target term → partial
      4. Partial match of alias                → alias_only
      5. Short/ambiguous terms                 → ambiguous
      6. MT has text but term not found        → missing

    Returns dict with check_result, error_type, actual_expression, note.
    """
    mt = str(mt_text or "").strip()
    required = str(required_target or "").strip()
    alias_list = [a for a in (aliases or []) if a.strip()]

    # ── No MT output ──
    if not mt:
        return {"check_result": "fail", "error_type": "missing",
                "actual_expression": "", "note": "MT text is empty"}

    # ── 1. Exact match of required target term ──
    if term_in_text(mt, required, target_lang):
        return {"check_result": "pass", "error_type": "none",
                "actual_expression": required, "note": ""}

    # ── 2. Exact match of alias (before partial match of target!) ──
    for alias in alias_list:
        if term_in_text(mt, alias, target_lang):
            return {"check_result": "fail", "error_type": "alias_only",
                    "actual_expression": alias,
                    "note": f"MT used alias '{alias}' instead of required '{required}'. Review: accept alias or enforce target term?"}

    # ── 3. Partial match of required target term ──
    partial_target = find_partial(required, mt, min_ratio=0.5)
    if partial_target:
        return {"check_result": "fail", "error_type": "partial",
                "actual_expression": partial_target,
                "note": f"Required '{required}' partially matched as '{partial_target}'"}

    # ── 4. Partial match of alias ──
    for alias in alias_list:
        partial_alias = find_partial(alias, mt, min_ratio=0.5)
        if partial_alias:
            return {"check_result": "fail", "error_type": "alias_only",
                    "actual_expression": partial_alias,
                    "note": f"MT partially used alias '{alias}' (matched: '{partial_alias}') instead of required '{required}'"}

    # ── 5. Ambiguous: short terms, common words, single chars ──
    if _is_ambiguous(required, source_term, source_lang):
        return {"check_result": "fail", "error_type": "ambiguous",
                "actual_expression": "",
                "note": f"Term too short/generic for reliable hard check. Source='{source_term}', Target='{required}'"}

    # ── 6. Missing ──
    return {"check_result": "fail", "error_type": "missing",
            "actual_expression": "",
            "note": f"'{required}' not found in MT output"}


def _is_ambiguous(target_term: str, source_term: str = "", source_lang: str = "") -> bool:
    """Check if a term is too short/generic for reliable hard TCR checking."""
    target = str(target_term or "").strip()
    source = str(source_term or "").strip()

    # Very short target terms
    if len(target) <= 1:
        return True
    if len(target) <= 2 and source_lang in ALPHABETIC_LANGS:
        return True

    # Very short source terms in alphabetic languages (single words like "approval", "seat")
    if source_lang in ALPHABETIC_LANGS and len(source) <= 6 and " " not in source:
        # Single short word → ambiguous in isolation
        # But proper nouns and abbreviations should NOT be ambiguous
        if source.isupper() and len(source) >= 2:
            return False  # Acronyms like "REESS", "SASO" are specific
        if len(source) <= 3:
            return True  # "van", "car", "bus" are too generic
        if source.lower() in _COMMON_WORDS:
            return True

    return False


# Common single words that are too generic for hard term checking
_COMMON_WORDS = {
    "approval", "seat", "test", "vehicle", "system", "part", "device",
    "component", "standard", "requirement", "section", "type", "model",
    "certificate", "regulation", "equipment", "barrier", "driver",
    "shall", "must", "may", "should", "can", "will",
}



def step3_tcr_hard_check(recall_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    对召回结果执行译后 TCR 硬校验。
    返回：(detail_df, batch_summary_df)
    """
    if recall_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    rows = []
    for _, rec in recall_df.iterrows():
        aliases = str(rec.get("aliases", "")).split("; ") if rec.get("aliases") else []
        aliases = [a.strip() for a in aliases if a.strip()]

        result = classify_error(
            required_target=str(rec["required_target_term"]),
            mt_text=str(rec.get("mt_text", "")),
            aliases=aliases,
            source_term=str(rec.get("matched_source_term", "")),
            source_lang=str(rec.get("source_lang", "")),
        )

        rows.append({
            **rec.to_dict(),
            "check_result": result["check_result"],
            "error_type": result["error_type"],
            "actual_expression": result["actual_expression"],
            "note": result["note"],
        })

    detail_df = pd.DataFrame(rows)

    # Batch summary
    summaries = []
    for lang in sorted(detail_df["source_lang"].unique()):
        ld = detail_df[detail_df["source_lang"] == lang]
        total = len(ld)
        passed = len(ld[ld["check_result"] == "pass"])
        failed = total - passed
        tcr = round(passed / total * 100, 2) if total > 0 else 0.0

        error_counts = ld["error_type"].value_counts().to_dict()

        rfp_info = RFP_LANGUAGES.get(lang, {})
        target_pct = round(rfp_info.get("target", 0) * 100, 0) if rfp_info else None

        summaries.append({
            "source_lang": lang,
            "lang_name": get_lang_name(lang),
            "is_rfp": is_rfp_language(lang),
            "rfp_target_pct": target_pct if target_pct else "",
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "hard_tcr": tcr,
            "gap_to_target": round(tcr - target_pct, 2) if target_pct else "",
            "missing": error_counts.get("missing", 0),
            "partial": error_counts.get("partial", 0),
            "alias_only": error_counts.get("alias_only", 0),
            "ambiguous": error_counts.get("ambiguous", 0),
        })

    batch_df = pd.DataFrame(summaries)

    # Sample-level summary
    if not detail_df.empty:
        sample_summary = detail_df.groupby(["sample_id", "source_lang"]).agg(
            source_text=("source_text", "first"),
            mt_text=("mt_text", "first"),
            total_hard_terms=("check_result", "count"),
            passed_terms=("check_result", lambda x: (x == "pass").sum()),
            failed_terms=("check_result", lambda x: (x != "pass").sum()),
            failed_term_list=("matched_source_term", lambda x: " | ".join(
                [str(t) for t, r in zip(x, detail_df.loc[x.index, "check_result"]) if r != "pass"]
            )),
        ).reset_index()
        sample_summary["sample_pass"] = sample_summary["failed_terms"] == 0
        sample_summary.to_csv(OUTPUT_DIR / "tcr_sample_summary.csv", index=False, encoding="utf-8-sig")

    passed_total = detail_df["check_result"].eq("pass").sum() if not detail_df.empty else 0
    total_total = len(detail_df)
    print(f"[Step 3] TCR Hard Check: {passed_total}/{total_total} passed "
          f"({round(passed_total/total_total*100,2)}%)" if total_total > 0 else "[Step 3] No data")

    return detail_df, batch_df


# ── Step 4: Failed Sample Intercept Queue ────────────────────────────────────

def step4_failed_queue(check_detail_df: pd.DataFrame) -> pd.DataFrame:
    """
    建立失败样本拦截队列。
    仅保留 check_result=fail 的，标注 retry_priority。
    """
    if check_detail_df.empty:
        return pd.DataFrame()

    failed = check_detail_df[check_detail_df["check_result"] == "fail"].copy()

    if failed.empty:
        print("[Step 4] No failed samples.")
        return failed

    # Assign retry priority based on error type
    priority_map = {
        "missing": "high",
        "partial": "high",
        "wrong_translation": "high",
        "alias_only": "medium",
        "ambiguous": "low",
    }
    failed["retry_priority"] = failed["error_type"].map(priority_map).fillna("medium")

    # Determine retry_needed
    failed["retry_needed"] = failed["error_type"].isin(["missing", "partial", "wrong_translation"])

    cols = [
        "sample_id", "source_lang", "source_text", "mt_text",
        "matched_source_term", "required_target_term",
        "actual_expression", "error_type",
        "retry_needed", "retry_priority", "note",
        "term_id", "domain",
    ]
    result = failed[[c for c in cols if c in failed.columns]]

    print(f"[Step 4] Failed Queue: {len(result)} failed terms "
          f"({result['retry_needed'].sum()} need retry)")
    return result


# ── Step 5: Directed Retry Sample Pool ───────────────────────────────────────

def step5_retry_pool(failed_df: pd.DataFrame) -> pd.DataFrame:
    """
    从失败队列中筛选定向重试样本池。
    retry_needed=True → 进入重试池
    """
    if failed_df.empty:
        return pd.DataFrame()

    retry = failed_df[failed_df["retry_needed"] == True].copy()

    if retry.empty:
        print("[Step 5] No samples for retry.")
        return retry

    # Per-sample aggregation for retry
    retry_pool = retry.groupby(["sample_id", "source_lang"]).agg(
        source_text=("source_text", "first"),
        current_translation=("mt_text", "first"),
        failed_source_terms=("matched_source_term", lambda x: " | ".join(x)),
        required_target_terms=("required_target_term", lambda x: " | ".join(x)),
        error_types=("error_type", lambda x: " | ".join(x)),
        retry_priority=("retry_priority", lambda x: "high" if "high" in x.values else ("medium" if "medium" in x.values else "low")),
        failed_count=("sample_id", "count"),
    ).reset_index()

    # Sort by priority then count
    priority_order = {"high": 0, "medium": 1, "low": 2}
    retry_pool["_order"] = retry_pool["retry_priority"].map(priority_order)
    retry_pool = retry_pool.sort_values(["_order", "failed_count"], ascending=[True, False])
    retry_pool = retry_pool.drop(columns=["_order"])

    print(f"[Step 5] Retry Sample Pool: {len(retry_pool)} samples")
    return retry_pool


# ── Step 6: Term Feedback Candidates ─────────────────────────────────────────

def step6_term_feedback(check_detail_df: pd.DataFrame, recall_df: pd.DataFrame) -> pd.DataFrame:
    """
    术语回流候选清单。
    汇总 alias_only、partial、ambiguous 等类型的问题术语。
    """
    if check_detail_df.empty:
        return pd.DataFrame()

    feedback_rows = []

    # Alias-only issues: alias exists but target term not used
    alias_issues = check_detail_df[check_detail_df["error_type"] == "alias_only"]
    if not alias_issues.empty:
        for term_id, grp in alias_issues.groupby("term_id"):
            feedback_rows.append({
                "term_id": term_id,
                "source_term": grp["matched_source_term"].iloc[0],
                "required_target_term": grp["required_target_term"].iloc[0],
                "available_aliases": grp["aliases"].iloc[0],
                "issue_type": "alias_maybe_upgrade",
                "occurrences": len(grp),
                "suggestion": "Consider adding alias as accepted variant or upgrading to formal target term",
                "source_langs": ", ".join(sorted(grp["source_lang"].unique())),
            })

    # Frequent missing terms (potential termbase issue)
    missing = check_detail_df[check_detail_df["error_type"] == "missing"]
    if not missing.empty:
        freq = missing.groupby(["term_id", "matched_source_term", "required_target_term"]).size().sort_values(ascending=False)
        for (tid, src, tgt), count in freq.head(20).items():
            langs = ", ".join(sorted(missing[missing["term_id"] == tid]["source_lang"].unique()))
            feedback_rows.append({
                "term_id": tid,
                "source_term": src,
                "required_target_term": tgt,
                "available_aliases": missing[missing["term_id"] == tid]["aliases"].iloc[0],
                "issue_type": "frequent_missing",
                "occurrences": count,
                "suggestion": "Check if target term is appropriate or if MT consistently prefers different translation",
                "source_langs": langs,
            })

    # Broad/short terms with high false positive rate
    ambiguous = check_detail_df[check_detail_df["error_type"] == "ambiguous"]
    if not ambiguous.empty:
        for term_id, grp in ambiguous.groupby("term_id"):
            if len(grp) >= 3:
                feedback_rows.append({
                    "term_id": term_id,
                    "source_term": grp["matched_source_term"].iloc[0],
                    "required_target_term": grp["required_target_term"].iloc[0],
                    "available_aliases": grp["aliases"].iloc[0],
                    "issue_type": "short_term_noise",
                    "occurrences": len(grp),
                    "suggestion": "Term too short/generic, consider removing from hard required or adding context constraints",
                    "source_langs": ", ".join(sorted(grp["source_lang"].unique())),
                })

    df = pd.DataFrame(feedback_rows)
    if not df.empty:
        df = df.sort_values(["issue_type", "occurrences"], ascending=[True, False])
    print(f"[Step 6] Term Feedback: {len(df)} candidate issues")
    return df


# ── Step 7: Pipeline Summary ─────────────────────────────────────────────────

def step7_pipeline_summary(
    hard_terms_df: pd.DataFrame,
    batch_summary: pd.DataFrame,
    failed_df: pd.DataFrame,
    retry_pool: pd.DataFrame,
    feedback_df: pd.DataFrame,
) -> str:
    """生成 Pipeline 执行小结."""
    lines = []
    lines.append("=" * 70)
    lines.append("TCR Hard Control Pipeline — 执行小结")
    lines.append("=" * 70)
    lines.append(f"Hard Required Terms: {hard_terms_df['hard_required'].sum()} terms (strict scope)")
    lines.append(f"Review Terms:       {(~hard_terms_df['hard_required']).sum()} terms (relaxed scope, not in hard control)")
    lines.append("")

    if not batch_summary.empty:
        lines.append("--- Batch-level Hard TCR ---")
        for _, r in batch_summary.iterrows():
            flag = "🔴" if r["is_rfp"] else "  "
            target_str = f" (target: {r['rfp_target_pct']:.0f}%)" if r["rfp_target_pct"] else ""
            gap_str = f" gap: {r['gap_to_target']:+.1f}pp" if r["gap_to_target"] != "" else ""
            lines.append(
                f"  {flag} {r['source_lang']:<5} {r['lang_name']:<12} "
                f"TCR: {r['hard_tcr']:.1f}%{target_str}{gap_str} "
                f"[{r['passed']}/{r['total_checks']}]"
            )
        lines.append("")

    rfp = batch_summary[batch_summary["is_rfp"] == True] if not batch_summary.empty else pd.DataFrame()
    if not rfp.empty:
        pass_count = len(rfp[rfp["hard_tcr"] >= rfp["rfp_target_pct"]])
        lines.append(f"RFP Hard TCR Pass: {pass_count}/{len(rfp)}")
        lines.append("")

    if not failed_df.empty:
        lines.append(f"Failed Term Hits: {len(failed_df)}")
        for et in ["missing", "partial", "alias_only", "ambiguous"]:
            cnt = len(failed_df[failed_df["error_type"] == et])
            if cnt > 0:
                lines.append(f"  - {et}: {cnt}")
        lines.append("")

    if not retry_pool.empty:
        lines.append(f"Retry Sample Pool: {len(retry_pool)} samples")
        high_n = len(retry_pool[retry_pool["retry_priority"] == "high"])
        lines.append(f"  - high priority: {high_n}")
        lines.append(f"  - medium priority: {len(retry_pool) - high_n}")
        lines.append("")

    if not feedback_df.empty:
        for issue_type in ["frequent_missing", "alias_maybe_upgrade", "short_term_noise"]:
            cnt = len(feedback_df[feedback_df["issue_type"] == issue_type])
            if cnt > 0:
                lines.append(f"Term Feedback ({issue_type}): {cnt} terms")
        lines.append("")

    lines.append("Pipeline complete. Output files in: " + str(OUTPUT_DIR))
    lines.append("=" * 70)

    text = "\n".join(lines)
    print(text)
    return text


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TCR Hard Control Pipeline")
    parser.add_argument("--langs", nargs="+", default=["en", "ru", "es", "de", "fr", "th", "ar"],
                        help="Languages to process (default: RFP 7)")
    parser.add_argument("--termbase", default="termbase/core_high_terms_v0.3_candidate.csv")
    parser.add_argument("--mt-root", default="data/mt/qwen-max-term")
    parser.add_argument("--model", default="qwen-max")
    parser.add_argument("--step", default="all",
                        choices=["all", "hard_terms", "recall", "check", "failed", "retry", "feedback"])
    parser.add_argument("--output-dir", default="data/report/tcr")
    args = parser.parse_args()

    langs = ALL_LANGS if args.langs == ["all"] else args.langs

    termbase_path = PROJECT_ROOT / args.termbase
    mt_root = PROJECT_ROOT / args.mt_root
    output_dir = PROJECT_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("TCR Hard Control Pipeline")
    print(f"Languages: {langs}")
    print(f"Termbase:  {termbase_path}")
    print(f"MT Root:   {mt_root}")
    print(f"Output:    {output_dir}")
    print("=" * 70)

    # Step 1: Hard Required Terms
    if args.step in ("all", "hard_terms"):
        print("\n── Step 1: Hard Required Terms ──")
        hard_terms_df = step1_hard_required_terms(termbase_path, langs)
        hard_terms_df.to_csv(output_dir / "hard_required_terms.csv", index=False, encoding="utf-8-sig")
    else:
        # Load existing
        p = output_dir / "hard_required_terms.csv"
        hard_terms_df = pd.read_csv(p) if p.exists() else pd.DataFrame()

    # Step 2: Source Term Recall
    if args.step in ("all", "recall"):
        print("\n── Step 2: Source Term Recall ──")
        mt_files = find_mt_files(mt_root, args.model, langs)
        if not mt_files:
            print("ERROR: No MT files found!")
            return 1
        print(f"Found MT files: {list(mt_files.keys())}")
        recall_df = step2_term_recall(termbase_path, mt_files)
        recall_df.to_csv(output_dir / "term_recall_detail.csv", index=False, encoding="utf-8-sig")
    else:
        p = output_dir / "term_recall_detail.csv"
        recall_df = pd.read_csv(p) if p.exists() else pd.DataFrame()
        if not recall_df.empty:
            # Fill aliases from hard_terms
            pass

    # Step 3: TCR Hard Check
    if args.step in ("all", "check"):
        print("\n── Step 3: TCR Hard Check ──")
        if not recall_df.empty:
            check_detail_df, batch_summary = step3_tcr_hard_check(recall_df)
            check_detail_df.to_csv(output_dir / "tcr_hard_check_detail.csv", index=False, encoding="utf-8-sig")
            batch_summary.to_csv(output_dir / "tcr_batch_summary.csv", index=False, encoding="utf-8-sig")
        else:
            print("No recall data — loading from disk")
            p = output_dir / "term_recall_detail.csv"
            if p.exists():
                recall_df = pd.read_csv(p)
                check_detail_df, batch_summary = step3_tcr_hard_check(recall_df)
                check_detail_df.to_csv(output_dir / "tcr_hard_check_detail.csv", index=False, encoding="utf-8-sig")
                batch_summary.to_csv(output_dir / "tcr_batch_summary.csv", index=False, encoding="utf-8-sig")
            else:
                check_detail_df, batch_summary = pd.DataFrame(), pd.DataFrame()
    else:
        p = output_dir / "tcr_hard_check_detail.csv"
        check_detail_df = pd.read_csv(p, dtype=str).fillna("") if p.exists() else pd.DataFrame()
        p2 = output_dir / "tcr_batch_summary.csv"
        batch_summary = pd.read_csv(p2) if p2.exists() else pd.DataFrame()

    # Step 4: Failed Queue
    if args.step in ("all", "failed"):
        print("\n── Step 4: Failed Sample Intercept Queue ──")
        failed_df = step4_failed_queue(check_detail_df)
        if not failed_df.empty:
            failed_df.to_csv(output_dir / "failed_sample_queue.csv", index=False, encoding="utf-8-sig")
    else:
        p = output_dir / "failed_sample_queue.csv"
        failed_df = pd.read_csv(p, dtype=str).fillna("") if p.exists() else pd.DataFrame()

    # Step 5: Retry Sample Pool
    if args.step in ("all", "retry"):
        print("\n── Step 5: Directed Retry Sample Pool ──")
        retry_pool = step5_retry_pool(failed_df)
        if not retry_pool.empty:
            retry_pool.to_csv(output_dir / "retry_sample_pool.csv", index=False, encoding="utf-8-sig")
    else:
        p = output_dir / "retry_sample_pool.csv"
        retry_pool = pd.read_csv(p, dtype=str).fillna("") if p.exists() else pd.DataFrame()

    # Step 6: Term Feedback
    if args.step in ("all", "feedback"):
        print("\n── Step 6: Term Feedback Candidates ──")
        feedback_df = step6_term_feedback(check_detail_df, recall_df)
        if not feedback_df.empty:
            feedback_df.to_csv(output_dir / "term_feedback_candidates.csv", index=False, encoding="utf-8-sig")
    else:
        p = output_dir / "term_feedback_candidates.csv"
        feedback_df = pd.read_csv(p, dtype=str).fillna("") if p.exists() else pd.DataFrame()

    # Step 7: Pipeline Summary
    print("\n── Step 7: Pipeline Summary ──")
    summary_text = step7_pipeline_summary(
        hard_terms_df, batch_summary, failed_df, retry_pool, feedback_df
    )
    with open(output_dir / "pipeline_summary.txt", "w", encoding="utf-8") as f:
        f.write(summary_text)

    # ── Final: Write Excel report ──
    excel_path = output_dir / "tcr_hard_pipeline_v1.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        if not hard_terms_df.empty:
            hard_terms_df.to_excel(writer, sheet_name="1_hard_required_terms", index=False)
        if not recall_df.empty:
            recall_df.to_excel(writer, sheet_name="2_term_recall_detail", index=False)
        if not check_detail_df.empty:
            check_detail_df.to_excel(writer, sheet_name="3_tcr_check_detail", index=False)
        if not batch_summary.empty:
            batch_summary.to_excel(writer, sheet_name="3_batch_summary", index=False)
        if not failed_df.empty:
            failed_df.to_excel(writer, sheet_name="4_failed_queue", index=False)
        if not retry_pool.empty:
            retry_pool.to_excel(writer, sheet_name="5_retry_pool", index=False)
        if not feedback_df.empty:
            feedback_df.to_excel(writer, sheet_name="6_term_feedback", index=False)

    print(f"\nPipeline complete. Excel report: {excel_path}")
    print(f"CSV outputs: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
