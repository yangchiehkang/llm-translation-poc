#!/usr/bin/env python3
"""参考语料对齐体检（只读，不修改语料）。

两类输出：
  1) 每语向 参考/源文 字符比值分布（mean/p10/p50/p90）+ 偏离本语向中位数 2 倍以上的条数/占比。
     每个语向的「正常比值」不同（中文紧凑；泰/阿对中文各有各的正常值），故阈值按各自中位数算。
  2) 缺陷四分类（条款号不匹配 / 源文切在半句 / PDF 抽取污染 / 表格行）——用 --dump-lang 打印某语向明细。

用法：
  python scripts/evaluation/align_health.py --inputs "data/eval/splits/reference_with_ref_300_by_lang/by_lang/*.jsonl"
  python scripts/evaluation/align_health.py --inputs "outputs/eval/en_zh_qwen36_20260723/full_results.jsonl" --dump-lang en-zh
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import statistics
from collections import defaultdict

# ---- 缺陷检测器 ----
_CLAUSE_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,6})")
# 源文以功能词/助动词/介词/连词结尾 = 疑似切在半句
_FUNC_END = {
    "be","is","are","was","were","shall","will","would","may","must","can","should","has","have","had",
    "and","or","of","the","a","an","to","with","for","in","on","at","by","from","as","that","which","this",
    "these","those","their","its","his","her","not","no","than","when","where","while","if","unless","into",
    "applying","containing","including","having","between","under","over","per","such","any","all","each",
}
_PDF_NOISE = re.compile(
    r"Download from|For reference purposes only|powered by|Applus|I\.R\.I\.S|\(cid:|IDIADA", re.IGNORECASE
)
# 下标被打散：如 "N , N and 1 2" / "M , M 1 2 3"
_SPLIT_SUB = re.compile(r"[A-Za-z]\s*,\s*[A-Za-z](?:\s+(?:and|,)\s+[A-Za-z])?\s+\d\s+\d")


def clause_no(text: str) -> str:
    m = _CLAUSE_RE.match(text or "")
    return m.group(1).rstrip(".") if m else ""


def is_half_sentence(src: str) -> bool:
    s = (src or "").strip()
    if not s:
        return False
    # 去掉尾部纯数字/标点残留后取最后一个字母词
    toks = re.findall(r"[A-Za-z]+", s)
    if toks and toks[-1].lower() in _FUNC_END:
        return True
    return False


def is_pdf_noise(src: str) -> bool:
    s = src or ""
    return bool(_PDF_NOISE.search(s) or _SPLIT_SUB.search(s))


def is_table_row(src: str) -> bool:
    s = (src or "").strip()
    if not s:
        return False
    body = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", s)  # 去掉开头的条款号再判断
    # 去掉条款号后仍以「数字 数字」开头，或数字字符占比很高且多段数字
    starts_numbers = bool(re.match(r"^\s*\d[\d.\s]{6,}\d", body))
    digit_ratio = sum(ch.isdigit() for ch in body) / max(len(body), 1)
    number_tokens = len(re.findall(r"\b\d+(?:\.\d+)?\b", body))
    return starts_numbers or (digit_ratio > 0.22 and number_tokens >= 4)


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * p / 100
    f = int(k); c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True, help="glob of jsonl files with source_text/ref_text/(language_pair)")
    ap.add_argument("--dump-lang", default="", help="打印该语向(如 en-zh)四类缺陷的 sample_id 明细")
    ap.add_argument("--dump-limit", type=int, default=1000)
    a = ap.parse_args()

    rows = []
    for path in sorted(glob.glob(a.inputs)):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            src = r.get("source_text") or r.get("source") or ""
            ref = r.get("ref_text") or r.get("reference") or r.get("ref") or ""
            if not src or not ref:
                continue
            pair = r.get("language_pair")
            if not pair:
                sid = str(r.get("sample_id") or "")
                m = re.search(r"_([a-z]{2}-[a-z]{2})_\d+", sid)
                pair = m.group(1) if m else "??"
            rows.append({"sample_id": r.get("sample_id"), "pair": pair, "src": src, "ref": ref})

    by = defaultdict(list)
    for r in rows:
        by[r["pair"]].append(r)

    print(f"{'lang':7}{'n':>5}{'ratio_mean':>11}{'p10':>7}{'p50':>7}{'p90':>7}{'>2x_med':>9}{'%':>6} | "
          f"{'clsMis':>7}{'halfSent':>9}{'pdfNoise':>9}{'table':>7}{'anyDef':>7}{'anyDef%':>8}")
    for pair in sorted(by):
        rs = by[pair]
        ratios = [len(r["ref"]) / len(r["src"]) for r in rs]
        med = statistics.median(ratios)
        dev2 = sum(1 for x in ratios if x > 2 * med or x < med / 2)
        cls = half = pdf = tbl = anyd = 0
        defs = {"clause_mismatch": [], "half_sentence": [], "pdf_noise": [], "table_row": []}
        for r in rs:
            cs, cr = clause_no(r["src"]), clause_no(r["ref"])
            fc = bool(cs and cr and cs != cr)
            fh = is_half_sentence(r["src"]); fp = is_pdf_noise(r["src"]); ft = is_table_row(r["src"])
            cls += fc; half += fh; pdf += fp; tbl += ft
            if fc: defs["clause_mismatch"].append(r["sample_id"])
            if fh: defs["half_sentence"].append(r["sample_id"])
            if fp: defs["pdf_noise"].append(r["sample_id"])
            if ft: defs["table_row"].append(r["sample_id"])
            if fc or fh or fp or ft: anyd += 1
        n = len(rs)
        print(f"{pair:7}{n:>5}{statistics.mean(ratios):>11.3f}{pct(ratios,10):>7.3f}{statistics.median(ratios):>7.3f}"
              f"{pct(ratios,90):>7.3f}{dev2:>9}{dev2/n*100:>5.0f}%"
              f" | {cls:>7}{half:>9}{pdf:>9}{tbl:>7}{anyd:>7}{anyd/n*100:>7.0f}%")
        if a.dump_lang and pair == a.dump_lang:
            print(f"\n===== {pair} 四类缺陷明细 (n={n}) =====")
            for k, ids in defs.items():
                print(f"\n--- {k}: {len(ids)} 条 ---")
                print(", ".join(str(x) for x in ids[:a.dump_limit]))


if __name__ == "__main__":
    main()
