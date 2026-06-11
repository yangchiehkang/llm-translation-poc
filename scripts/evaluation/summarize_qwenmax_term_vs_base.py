# -*- coding: utf-8 -*-
"""
summarize_qwenmax_term_vs_base.py

功能：
1. 汇总 Qwen-Max baseline 与 Qwen-Max + term prompt 的 XCOMET-XXL-QE 结果；
2. 统一语言名称，避免出现 “未知语言(portuguese)” 等情况；
3. 将 SourceLang / src2zh / sourcelanguage2zh 修正为越南语 vi2zh；
4. 汇总术语覆盖率、术语命中/非命中质量差异、失败样本；
5. 只输出 Excel 文件。

运行方式：
cd E:\\Working\\llm-translation-poc
python scripts\\evaluation\\summarize_qwenmax_term_vs_base.py
"""

import argparse
import re
from pathlib import Path
from typing import Dict, Optional, List

import pandas as pd


# ============================================================
# 1. 语言映射配置
# ============================================================

LANG_INFO = {
    "en": {
        "zh": "英语",
        "en": "English",
        "code": "en",
        "pair": "en2zh",
        "aliases": ["英语", "English", "en", "eng", "en2zh"],
    },
    "ru": {
        "zh": "俄语",
        "en": "Russian",
        "code": "ru",
        "pair": "ru2zh",
        "aliases": ["俄语", "Russian", "ru", "rus", "ru2zh"],
    },
    "de": {
        "zh": "德语",
        "en": "German",
        "code": "de",
        "pair": "de2zh",
        "aliases": ["德语", "German", "de", "deu", "ger", "de2zh"],
    },
    "fr": {
        "zh": "法语",
        "en": "French",
        "code": "fr",
        "pair": "fr2zh",
        "aliases": ["法语", "French", "fr", "fra", "fre", "fr2zh"],
    },
    "es": {
        "zh": "西班牙语",
        "en": "Spanish",
        "code": "es",
        "pair": "es2zh",
        "aliases": ["西班牙语", "Spanish", "es", "spa", "es2zh"],
    },
    "th": {
        "zh": "泰语",
        "en": "Thai",
        "code": "th",
        "pair": "th2zh",
        "aliases": ["泰语", "Thai", "th", "tha", "th2zh"],
    },
    "ar": {
        "zh": "阿拉伯语",
        "en": "Arabic",
        "code": "ar",
        "pair": "ar2zh",
        "aliases": ["阿拉伯语", "Arabic", "ar", "ara", "ar2zh"],
    },
    "ms": {
        "zh": "马来语",
        "en": "Malay",
        "code": "ms",
        "pair": "ms2zh",
        "aliases": ["马来语", "Malay", "ms", "msa", "ms2zh"],
    },
    "pt": {
        "zh": "葡萄牙语",
        "en": "Portuguese",
        "code": "pt",
        "pair": "pt2zh",
        "aliases": [
            "葡萄牙语",
            "Portuguese",
            "pt",
            "por",
            "pt2zh",
            "portuguese",
            "portuguese2zh",
            "未知语言(portuguese)",
        ],
    },
    "vi": {
        "zh": "越南语",
        "en": "Vietnamese",
        "code": "vi",
        "pair": "vi2zh",
        "aliases": [
            "越南语",
            "Vietnamese",
            "vi",
            "vie",
            "vi2zh",
            "vietnamese",
            "vietnamese2zh",
            "未知语言(vietnamese)",

            # 关键修复：baseline 里这一行实际是越南语
            "SourceLang",
            "sourcelang",
            "source_lang",
            "src",
            "src2zh",
            "sourcelang2zh",
            "sourcelanguage",
            "sourcelanguage2zh",
            "SourceLanguage",
            "SourceLanguage2zh",
            "未知语言(sourcelang)",
            "未知语言(sourcelanguage)",
        ],
    },
    "id": {
        "zh": "印尼语",
        "en": "Indonesian",
        "code": "id",
        "pair": "id2zh",
        "aliases": [
            "印尼语",
            "印度尼西亚语",
            "Indonesian",
            "id",
            "ind",
            "id2zh",
            "indonesian",
            "indonesian2zh",
            "未知语言(indonesian)",
        ],
    },
    "nl": {
        "zh": "荷兰语",
        "en": "Dutch",
        "code": "nl",
        "pair": "nl2zh",
        "aliases": [
            "荷兰语",
            "Dutch",
            "nl",
            "nld",
            "dut",
            "nl2zh",
            "dutch",
            "dutch2zh",
            "未知语言(dutch)",
        ],
    },
    "no": {
        "zh": "挪威语",
        "en": "Norwegian",
        "code": "no",
        "pair": "no2zh",
        "aliases": [
            "挪威语",
            "Norwegian",
            "no",
            "nor",
            "no2zh",
            "norwegian",
            "norwegian2zh",
            "未知语言(norwegian)",
        ],
    },
    "sv": {
        "zh": "瑞典语",
        "en": "Swedish",
        "code": "sv",
        "pair": "sv2zh",
        "aliases": [
            "瑞典语",
            "Swedish",
            "sv",
            "swe",
            "sv2zh",
            "swedish",
            "swedish2zh",
            "未知语言(swedish)",
        ],
    },
    "it": {
        "zh": "意大利语",
        "en": "Italian",
        "code": "it",
        "pair": "it2zh",
        "aliases": [
            "意大利语",
            "Italian",
            "it",
            "ita",
            "it2zh",
            "italian",
            "italian2zh",
            "未知语言(italian)",
        ],
    },
}


def build_alias_map() -> Dict[str, str]:
    alias_map = {}
    for code, info in LANG_INFO.items():
        for alias in info["aliases"]:
            alias_map[str(alias).strip().lower()] = code
    return alias_map


ALIAS_MAP = build_alias_map()


def normalize_lang(value: object) -> Optional[str]:
    """
    将各种语言名称/语言对/未知语言(...) 统一映射到标准 code。
    """
    if value is None or pd.isna(value):
        return None

    raw = str(value).strip()
    if not raw:
        return None

    key = raw.lower().strip()

    # 直接匹配 alias
    if key in ALIAS_MAP:
        return ALIAS_MAP[key]

    # 关键兜底：各种 source language 写法统一认为是越南语
    source_lang_keys = {
        "sourcelang",
        "sourcelanguage",
        "source_lang",
        "src",
        "src2zh",
        "sourcelang2zh",
        "sourcelanguage2zh",
        "source language",
        "source language2zh",
    }
    if key in source_lang_keys:
        return "vi"

    # 处理 xx2zh / portuguese2zh / dutch2zh
    m = re.match(r"^([a-zA-Z_]+)2zh$", key)
    if m:
        prefix = m.group(1).strip().lower()

        if prefix in source_lang_keys:
            return "vi"

        if prefix in ALIAS_MAP:
            return ALIAS_MAP[prefix]

        if prefix in LANG_INFO:
            return prefix

    # 处理 未知语言(xxx)
    m = re.match(r"^未知语言\((.*?)\)$", raw)
    if m:
        inner = m.group(1).strip().lower()

        if inner in source_lang_keys:
            return "vi"

        return ALIAS_MAP.get(inner)

    return None


def lang_zh(code: Optional[str]) -> Optional[str]:
    return LANG_INFO[code]["zh"] if code in LANG_INFO else None


def lang_en(code: Optional[str]) -> Optional[str]:
    return LANG_INFO[code]["en"] if code in LANG_INFO else None


def lang_pair(code: Optional[str]) -> Optional[str]:
    return LANG_INFO[code]["pair"] if code in LANG_INFO else None


def add_lang_columns(df: pd.DataFrame, lang_col_candidates: List[str]) -> pd.DataFrame:
    """
    给 DataFrame 增加标准语言列：
    - lang_code
    - lang_zh
    - lang_en
    - lang_pair_std
    """
    df = df.copy()

    source_col = None
    for col in lang_col_candidates:
        if col in df.columns:
            source_col = col
            break

    if source_col is None:
        df["lang_code"] = None
    else:
        df["lang_code"] = df[source_col].apply(normalize_lang)

    # 用 lang_pair 补充识别
    if "lang_pair" in df.columns:
        df["lang_code"] = df.apply(
            lambda row: row["lang_code"]
            if pd.notna(row["lang_code"])
            else normalize_lang(row.get("lang_pair")),
            axis=1,
        )

    # 用 _lang 补充识别
    if "_lang" in df.columns:
        df["lang_code"] = df.apply(
            lambda row: row["lang_code"]
            if pd.notna(row["lang_code"])
            else normalize_lang(row.get("_lang")),
            axis=1,
        )

    df["lang_zh"] = df["lang_code"].apply(lang_zh)
    df["lang_en"] = df["lang_code"].apply(lang_en)
    df["lang_pair_std"] = df["lang_code"].apply(lang_pair)

    return df


# ============================================================
# 2. 通用读表工具
# ============================================================

def safe_read_excel(path: Path, sheet_name=0) -> Optional[pd.DataFrame]:
    """
    安全读取单个 Excel sheet。
    """
    if not path.exists():
        print(f"[WARN] 文件不存在，跳过：{path}")
        return None

    try:
        obj = pd.read_excel(path, sheet_name=sheet_name)

        if isinstance(obj, dict):
            if not obj:
                return pd.DataFrame()
            first_sheet_name = list(obj.keys())[0]
            print(f"[INFO] {path.name} 返回多 Sheet，默认读取第一个 Sheet：{first_sheet_name}")
            return obj[first_sheet_name]

        return obj

    except Exception as e:
        print(f"[WARN] 读取 Excel 失败：{path}，原因：{e}")
        return None


def safe_read_excel_all_sheets(path: Path) -> Dict[str, pd.DataFrame]:
    """
    安全读取 Excel 所有 Sheet。
    """
    if not path.exists():
        print(f"[WARN] 文件不存在，跳过：{path}")
        return {}

    try:
        return pd.read_excel(path, sheet_name=None)
    except Exception as e:
        print(f"[WARN] 读取 Excel 多 Sheet 失败：{path}，原因：{e}")
        return {}


def to_number(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    df = df.copy()
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ============================================================
# 3. 解析 QE 总表
# ============================================================

def extract_summary_from_qe_report(xlsx_path: Path, label: str) -> pd.DataFrame:
    """
    从 qwen-max_xcomet-xxl-qe.xlsx 或 qwen_max_term_prompt_xcomet_xxl_qe.xlsx 中
    尝试提取语言级 summary。
    """
    sheets = safe_read_excel_all_sheets(xlsx_path)
    if not sheets:
        return pd.DataFrame()

    summary_candidates = []

    for sheet_name, df in sheets.items():
        if df is None or df.empty:
            continue

        cols = set(df.columns)

        has_summary_cols = (
            ("mean" in cols or "Mean" in cols or "Mean Score" in cols)
            and ("n" in cols or "N" in cols or "count" in cols or "N (Segments)" in cols)
            and (
                "lang_pair" in cols
                or "Pair" in cols
                or "pair" in cols
                or "Source Language" in cols
                or "Source Lang" in cols
                or "src_lang" in cols
            )
        )

        if has_summary_cols:
            tmp = df.copy()
            tmp["source_sheet"] = sheet_name
            summary_candidates.append(tmp)

    if not summary_candidates:
        print(f"[WARN] 未在 {xlsx_path.name} 中识别到语言级 summary。")
        return pd.DataFrame()

    raw = pd.concat(summary_candidates, ignore_index=True)

    rename_map = {
        "Source Language": "src_lang",
        "Source Lang": "src_lang",
        "source_lang": "src_lang",
        "Pair": "lang_pair",
        "pair": "lang_pair",
        "N": "n",
        "N (Segments)": "n",
        "count": "n",
        "Mean Score": "mean",
        "Mean": "mean",
        "Std Dev": "std",
        "Std": "std",
        "Min": "min",
        "Max": "max",
        "P05": "p05",
        "P10": "p10",
    }

    raw = raw.rename(columns={k: v for k, v in rename_map.items() if k in raw.columns})

    raw = add_lang_columns(
        raw,
        ["src_lang", "lang", "_lang", "Source Language", "Source Lang"],
    )

    # 如果有 lang_pair，再强制用 lang_pair 修正一次
    # 例如 src_lang = 未知语言，lang_pair = sourcelanguage2zh
    if "lang_pair" in raw.columns:
        raw["lang_code_from_pair"] = raw["lang_pair"].apply(normalize_lang)
        raw["lang_code"] = raw.apply(
            lambda row: row["lang_code_from_pair"]
            if pd.notna(row["lang_code_from_pair"])
            else row["lang_code"],
            axis=1,
        )
        raw["lang_zh"] = raw["lang_code"].apply(lang_zh)
        raw["lang_en"] = raw["lang_code"].apply(lang_en)
        raw["lang_pair_std"] = raw["lang_code"].apply(lang_pair)
        raw = raw.drop(columns=["lang_code_from_pair"], errors="ignore")

    for col in ["n", "mean", "std", "min", "p05", "p10", "max"]:
        if col not in raw.columns:
            raw[col] = None

    raw = to_number(raw, ["n", "mean", "std", "min", "p05", "p10", "max"])
    raw = raw[raw["lang_code"].notna()].copy()

    if raw.empty:
        return pd.DataFrame()

    out = (
        raw.groupby(["lang_code", "lang_zh", "lang_en", "lang_pair_std"], dropna=False)
        .agg(
            n=("n", "max"),
            mean=("mean", "mean"),
            std=("std", "mean"),
            min=("min", "min"),
            p05=("p05", "mean"),
            p10=("p10", "mean"),
            max=("max", "max"),
        )
        .reset_index()
    )

    out["experiment"] = label

    order_cols = [
        "experiment",
        "lang_code",
        "lang_zh",
        "lang_en",
        "lang_pair_std",
        "n",
        "mean",
        "std",
        "min",
        "p05",
        "p10",
        "max",
    ]
    return out[order_cols]


# ============================================================
# 4. 解析 term-prompt analysis summary
# ============================================================

def parse_term_analysis_summary(summary_path: Path) -> Dict[str, pd.DataFrame]:
    """
    读取 qwen_max_term_prompt_analysis_summary.xlsx 的所有 sheet，
    并对语言字段进行统一映射。
    """
    sheets = safe_read_excel_all_sheets(summary_path)
    results = {}

    for name, df in sheets.items():
        if df is None or df.empty:
            results[name] = pd.DataFrame()
            continue

        tmp = df.copy()
        tmp = add_lang_columns(tmp, ["src_lang", "_lang", "lang", "Source Lang", "Source Language"])

        if "lang_pair" in tmp.columns:
            tmp["lang_code_from_pair"] = tmp["lang_pair"].apply(normalize_lang)
            tmp["lang_code"] = tmp.apply(
                lambda row: row["lang_code_from_pair"]
                if pd.notna(row["lang_code_from_pair"])
                else row["lang_code"],
                axis=1,
            )
            tmp["lang_zh"] = tmp["lang_code"].apply(lang_zh)
            tmp["lang_en"] = tmp["lang_code"].apply(lang_en)
            tmp["lang_pair_std"] = tmp["lang_code"].apply(lang_pair)
            tmp = tmp.drop(columns=["lang_code_from_pair"], errors="ignore")

        results[name] = tmp

    return results


# ============================================================
# 5. 解析 metadata 与 failed rows
# ============================================================

def parse_metadata(metadata_path: Path) -> pd.DataFrame:
    df = safe_read_excel(metadata_path, sheet_name=0)

    if df is None or df.empty:
        return pd.DataFrame()

    df = add_lang_columns(df, ["src_lang_code", "_lang", "lang", "src_lang", "Source Lang"])

    if "matched_term_count" in df.columns:
        df["matched_term_count"] = (
            pd.to_numeric(df["matched_term_count"], errors="coerce")
            .fillna(0)
            .astype(int)
        )
        df["has_term_match"] = df["matched_term_count"] > 0
    elif "matched_terms" in df.columns:
        df["has_term_match"] = (
            df["matched_terms"]
            .fillna("")
            .astype(str)
            .apply(lambda x: x not in ["", "[]", "nan", "None"])
        )
    else:
        df["has_term_match"] = False

    return df


def parse_failed_rows(failed_path: Path) -> pd.DataFrame:
    df = safe_read_excel(failed_path, sheet_name=0)

    if df is None or df.empty:
        return pd.DataFrame()

    df = add_lang_columns(df, ["src_lang_code", "_lang", "lang", "src_lang", "Source Lang"])

    if "_reason" not in df.columns:
        df["_reason"] = "unknown"

    return df


def summarize_failed_rows(failed_df: pd.DataFrame) -> pd.DataFrame:
    if failed_df.empty:
        return pd.DataFrame(
            columns=[
                "lang_code",
                "lang_zh",
                "lang_en",
                "lang_pair_std",
                "failed_rows",
                "reasons",
            ]
        )

    return (
        failed_df.groupby(["lang_code", "lang_zh", "lang_en", "lang_pair_std"], dropna=False)
        .agg(
            failed_rows=("_reason", "count"),
            reasons=("_reason", lambda x: "; ".join(sorted(set(map(str, x))))),
        )
        .reset_index()
        .sort_values(["failed_rows", "lang_code"], ascending=[False, True])
    )


# ============================================================
# 6. 生成对比汇总
# ============================================================

def compare_base_vs_term(base_summary: pd.DataFrame, term_summary: pd.DataFrame) -> pd.DataFrame:
    if base_summary.empty and term_summary.empty:
        return pd.DataFrame()

    join_cols = ["lang_code", "lang_zh", "lang_en", "lang_pair_std"]

    base = base_summary.copy()
    term = term_summary.copy()

    if not base.empty:
        base = base.rename(
            columns={
                "n": "base_n",
                "mean": "base_mean",
                "std": "base_std",
                "min": "base_min",
                "p05": "base_p05",
                "p10": "base_p10",
                "max": "base_max",
            }
        )
    else:
        base = pd.DataFrame(columns=join_cols)

    if not term.empty:
        term = term.rename(
            columns={
                "n": "term_n",
                "mean": "term_mean",
                "std": "term_std",
                "min": "term_min",
                "p05": "term_p05",
                "p10": "term_p10",
                "max": "term_max",
            }
        )
    else:
        term = pd.DataFrame(columns=join_cols)

    base_cols = join_cols + [
        "base_n",
        "base_mean",
        "base_std",
        "base_min",
        "base_p05",
        "base_p10",
        "base_max",
    ]
    term_cols = join_cols + [
        "term_n",
        "term_mean",
        "term_std",
        "term_min",
        "term_p05",
        "term_p10",
        "term_max",
    ]

    for col in base_cols:
        if col not in base.columns:
            base[col] = None

    for col in term_cols:
        if col not in term.columns:
            term[col] = None

    merged = base[base_cols].merge(
        term[term_cols],
        on=join_cols,
        how="outer",
    )

    merged["mean_delta"] = merged["term_mean"] - merged["base_mean"]
    merged["relative_delta_pct"] = merged["mean_delta"] / merged["base_mean"] * 100

    def judge(delta):
        if pd.isna(delta):
            return "unknown"
        if delta > 0.01:
            return "improved"
        if delta < -0.01:
            return "degraded"
        return "flat"

    merged["effect_label"] = merged["mean_delta"].apply(judge)

    # 排序：核心语种靠前，其余按 term_mean 排
    lang_order = {
        "en": 1,
        "ru": 2,
        "de": 3,
        "fr": 4,
        "es": 5,
        "th": 6,
        "ar": 7,
        "ms": 8,
        "id": 9,
        "pt": 10,
        "vi": 11,
        "nl": 12,
        "no": 13,
        "sv": 14,
        "it": 15,
    }
    merged["sort_order"] = merged["lang_code"].map(lang_order).fillna(999)
    merged = merged.sort_values(["sort_order", "lang_code"]).drop(columns=["sort_order"])

    return merged


def build_term_coverage_summary(term_analysis_sheets: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    df = term_analysis_sheets.get("term_coverage", pd.DataFrame())
    if df.empty:
        return pd.DataFrame()

    out = df.copy()

    for col in ["valid_rows", "term_matched_rows", "non_term_rows", "term_match_ratio"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    keep_cols = [
        "lang_code",
        "lang_zh",
        "lang_en",
        "lang_pair_std",
        "valid_rows",
        "term_matched_rows",
        "non_term_rows",
        "term_match_ratio",
    ]

    for col in keep_cols:
        if col not in out.columns:
            out[col] = None

    out = out[keep_cols].copy()
    out = out.sort_values("term_match_ratio", ascending=False)

    return out


def build_term_vs_nonterm_summary(term_analysis_sheets: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    df = term_analysis_sheets.get("by_lang_term_vs_nonterm", pd.DataFrame())
    if df.empty:
        return pd.DataFrame()

    out = df.copy()

    for col in ["count", "mean", "median", "std", "min", "max"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    keep_cols = [
        "lang_code",
        "lang_zh",
        "lang_en",
        "lang_pair_std",
        "term_group",
        "has_term_match",
        "count",
        "mean",
        "median",
        "std",
        "min",
        "max",
    ]

    for col in keep_cols:
        if col not in out.columns:
            out[col] = None

    out = out[keep_cols].copy()
    out = out.sort_values(["lang_code", "has_term_match"])

    return out


def pivot_term_vs_nonterm(term_vs_nonterm: pd.DataFrame) -> pd.DataFrame:
    if term_vs_nonterm.empty:
        return pd.DataFrame()

    df = term_vs_nonterm.copy()

    def group_key(x):
        if isinstance(x, str):
            return "term" if x.strip().lower() in ["true", "1", "yes"] else "nonterm"
        return "term" if bool(x) else "nonterm"

    df["group_key"] = df["has_term_match"].apply(group_key)

    pivot = df.pivot_table(
        index=["lang_code", "lang_zh", "lang_en", "lang_pair_std"],
        columns="group_key",
        values=["count", "mean", "median", "std", "min", "max"],
        aggfunc="first",
    )

    pivot.columns = [f"{metric}_{group}" for metric, group in pivot.columns]
    pivot = pivot.reset_index()

    if "mean_term" in pivot.columns and "mean_nonterm" in pivot.columns:
        pivot["term_minus_nonterm_mean"] = pivot["mean_term"] - pivot["mean_nonterm"]

    if "median_term" in pivot.columns and "median_nonterm" in pivot.columns:
        pivot["term_minus_nonterm_median"] = pivot["median_term"] - pivot["median_nonterm"]

    if "term_minus_nonterm_mean" in pivot.columns:
        pivot = pivot.sort_values("term_minus_nonterm_mean", ascending=False)

    return pivot


def build_valid_rows_summary(metadata_df: pd.DataFrame) -> pd.DataFrame:
    if metadata_df.empty:
        return pd.DataFrame()

    count_col = "seg_id" if "seg_id" in metadata_df.columns else "lang_code"

    summary = (
        metadata_df.groupby(["lang_code", "lang_zh", "lang_en", "lang_pair_std"], dropna=False)
        .agg(
            valid_rows=(count_col, "count"),
            term_matched_rows=("has_term_match", "sum"),
        )
        .reset_index()
    )

    summary["non_term_rows"] = summary["valid_rows"] - summary["term_matched_rows"]
    summary["term_match_ratio"] = summary["term_matched_rows"] / summary["valid_rows"]

    return summary.sort_values("term_match_ratio", ascending=False)


# ============================================================
# 7. 主流程：只输出 Excel
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=str,
        default=r"E:\Working\llm-translation-poc",
        help=r"项目根目录，默认：E:\Working\llm-translation-poc",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root)

    base_qe_path = (
        project_root
        / "data"
        / "report"
        / "xcomet-xxl-qwenmax"
        / "qwen-max_xcomet-xxl-qe.xlsx"
    )

    term_dir = (
        project_root
        / "data"
        / "report"
        / "xcomet-xxl-qe"
        / "term-prompt"
    )

    term_summary_path = term_dir / "qwen_max_term_prompt_analysis_summary.xlsx"
    term_qe_path = term_dir / "qwen_max_term_prompt_xcomet_xxl_qe.xlsx"
    metadata_path = term_dir / "metadata" / "qwen_max_term_prompt_valid_rows_metadata.xlsx"
    failed_path = term_dir / "failed_rows" / "qwen_max_term_prompt_failed_rows.xlsx"

    out_dir = (
        project_root
        / "data"
        / "report"
        / "xcomet-xxl-qe"
        / "compare"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    output_xlsx = out_dir / "qwenmax_base_vs_term_summary.xlsx"

    print("[INFO] 项目根目录：", project_root)
    print("[INFO] 输出 Excel：", output_xlsx)

    # 1. 读取 baseline
    print("[INFO] 读取 baseline QE summary...")
    base_summary = extract_summary_from_qe_report(
        base_qe_path,
        label="qwen-max-base",
    )

    # 2. 读取 term-prompt QE
    print("[INFO] 读取 term-prompt QE summary...")
    term_qe_summary = extract_summary_from_qe_report(
        term_qe_path,
        label="qwen-max-term-prompt",
    )

    # 3. 读取 term analysis summary
    print("[INFO] 读取 term analysis summary...")
    term_analysis_sheets = parse_term_analysis_summary(term_summary_path)

    # 如果 term_qe_summary 没解析出来，就从 analysis summary 的 xcomet_summary_by_lang 提取
    if term_qe_summary.empty and "xcomet_summary_by_lang" in term_analysis_sheets:
        print("[INFO] 从 analysis summary 的 xcomet_summary_by_lang 提取 term-prompt summary...")

        tmp = term_analysis_sheets["xcomet_summary_by_lang"].copy()

        for col in ["n", "mean", "std", "min", "p05", "p10", "max"]:
            if col in tmp.columns:
                tmp[col] = pd.to_numeric(tmp[col], errors="coerce")
            else:
                tmp[col] = None

        term_qe_summary = (
            tmp.groupby(["lang_code", "lang_zh", "lang_en", "lang_pair_std"], dropna=False)
            .agg(
                n=("n", "max"),
                mean=("mean", "mean"),
                std=("std", "mean"),
                min=("min", "min"),
                p05=("p05", "mean"),
                p10=("p10", "mean"),
                max=("max", "max"),
            )
            .reset_index()
        )
        term_qe_summary["experiment"] = "qwen-max-term-prompt"

    # 4. base vs term
    print("[INFO] 生成 base vs term 对比...")
    compare_df = compare_base_vs_term(base_summary, term_qe_summary)

    # 5. 术语相关汇总
    print("[INFO] 生成术语覆盖率与术语命中质量对比...")
    term_coverage = build_term_coverage_summary(term_analysis_sheets)
    term_vs_nonterm = build_term_vs_nonterm_summary(term_analysis_sheets)
    term_vs_nonterm_pivot = pivot_term_vs_nonterm(term_vs_nonterm)

    # 6. metadata / failed rows
    print("[INFO] 读取 metadata 与 failed rows...")
    metadata_df = parse_metadata(metadata_path)
    metadata_summary = build_valid_rows_summary(metadata_df)

    failed_df = parse_failed_rows(failed_path)
    failed_summary = summarize_failed_rows(failed_df)

    # 7. 输出 Excel
    print("[INFO] 写入 Excel...")

    with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
        if not compare_df.empty:
            compare_df.to_excel(writer, sheet_name="base_vs_term", index=False)

        if not base_summary.empty:
            base_summary.to_excel(writer, sheet_name="base_summary_norm", index=False)

        if not term_qe_summary.empty:
            term_qe_summary.to_excel(writer, sheet_name="term_summary_norm", index=False)

        if not term_coverage.empty:
            term_coverage.to_excel(writer, sheet_name="term_coverage_norm", index=False)

        if not term_vs_nonterm.empty:
            term_vs_nonterm.to_excel(writer, sheet_name="term_vs_nonterm", index=False)

        if not term_vs_nonterm_pivot.empty:
            term_vs_nonterm_pivot.to_excel(writer, sheet_name="term_vs_nonterm_pivot", index=False)

        if not metadata_summary.empty:
            metadata_summary.to_excel(writer, sheet_name="metadata_valid_summary", index=False)

        if not failed_summary.empty:
            failed_summary.to_excel(writer, sheet_name="failed_summary", index=False)

        if not failed_df.empty:
            failed_df.to_excel(writer, sheet_name="failed_rows_norm", index=False)

    print("[DONE] 汇总完成。")
    print(f"[DONE] Excel: {output_xlsx}")


if __name__ == "__main__":
    main()
