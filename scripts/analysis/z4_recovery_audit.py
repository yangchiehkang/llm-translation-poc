#!/usr/bin/env python3
"""Material->product 字符回收率审计（2026-07-29，Task A）。

对 7 个语向的每份文档、源文/参考译文两侧分别追踪 5 个抽取阶段的字符数：
① 原始 PDF（pdfplumber 抽取原文）
② 分段后（parse_pdf_segments 输出）
③ 带 section_no 的段
④ 对齐后（align_segments 输出，含全部对齐方式）
⑤ 排除规则后（da_prefilter_reason 全部通过的最终可用集）

只读，不修改任何产物文件；跑一次 --mode from_raw 同款的抽取/对齐逻辑，
直接调用 prepare_da_pairs.py 里的函数，保证与生产链路完全一致。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluation.prepare_da_pairs import (
    align_segments,
    da_prefilter_reason,
    extract_pages,
    load_raw_groups,
    parse_pdf_segments,
)

RAW_DIR = PROJECT_ROOT / "data" / "raw"
MIN_SOURCE_CHARS = 30
MIN_REF_CHARS = 2
MAX_SEGMENT_CHARS = 3000


def stage1_chars(pdf_path: Path) -> tuple[int, int]:
    pages = extract_pages(pdf_path)
    total = sum(len(p.get("text") or "") for p in pages)
    return len(pages), total


def audit_side(pdf_path: Path, document_id: str, language_pair: str, lang: str, min_chars: int):
    page_count, s1_chars = stage1_chars(pdf_path)
    segments, filtered_lines, notes = parse_pdf_segments(
        pdf_path, document_id, language_pair, lang, min_chars=min_chars, max_chars=MAX_SEGMENT_CHARS
    )
    s2_count = len(segments)
    s2_chars = sum(seg["char_count"] for seg in segments)
    with_section = [seg for seg in segments if seg.get("section_no")]
    s3_count = len(with_section)
    s3_chars = sum(seg["char_count"] for seg in with_section)
    return {
        "page_count": page_count,
        "s1_chars": s1_chars,
        "segments": segments,
        "s2_count": s2_count,
        "s2_chars": s2_chars,
        "s3_count": s3_count,
        "s3_chars": s3_chars,
        "filtered_lines": filtered_lines,
    }


def main() -> None:
    groups = load_raw_groups(RAW_DIR)
    by_doc: dict[str, dict] = {}
    by_lang_agg: dict[str, dict] = {}

    for group in sorted(groups, key=lambda g: (g["language_pair"], g["document_id"])):
        pair = group["language_pair"]
        doc_id = group["document_id"]
        print(f"[audit] {pair} {doc_id}", file=sys.stderr, flush=True)

        src = audit_side(Path(group["source_pdf"]), doc_id, pair, group["source_lang"], MIN_SOURCE_CHARS)
        ref = audit_side(Path(group["reference_pdf"]), doc_id, pair, group["target_lang"], MIN_REF_CHARS)

        aligned = align_segments(src["segments"], ref["segments"], group, MIN_SOURCE_CHARS)
        s4_count = len(aligned)
        s4_src_chars = sum(a["source_char_count"] for a in aligned)
        s4_ref_chars = sum(a["ref_char_count"] for a in aligned)

        reasons = [da_prefilter_reason(a) for a in aligned]
        kept = [a for a, r in zip(aligned, reasons) if r is None]
        s5_count = len(kept)
        s5_src_chars = sum(a["source_char_count"] for a in kept)
        s5_ref_chars = sum(a["ref_char_count"] for a in kept)

        exclude_reasons = {}
        for r in reasons:
            if r is not None:
                exclude_reasons[r] = exclude_reasons.get(r, 0) + 1

        doc_record = {
            "language_pair": pair,
            "document_id": doc_id,
            "source": {
                "page_count": src["page_count"],
                "s1_chars": src["s1_chars"],
                "s2_count": src["s2_count"],
                "s2_chars": src["s2_chars"],
                "s3_count": src["s3_count"],
                "s3_chars": src["s3_chars"],
            },
            "reference": {
                "page_count": ref["page_count"],
                "s1_chars": ref["s1_chars"],
                "s2_count": ref["s2_count"],
                "s2_chars": ref["s2_chars"],
                "s3_count": ref["s3_count"],
                "s3_chars": ref["s3_chars"],
            },
            "s4_count": s4_count,
            "s4_src_chars": s4_src_chars,
            "s4_ref_chars": s4_ref_chars,
            "s5_count": s5_count,
            "s5_src_chars": s5_src_chars,
            "s5_ref_chars": s5_ref_chars,
            "exclude_reasons": exclude_reasons,
        }
        by_doc[f"{pair}/{doc_id}"] = doc_record

        agg = by_lang_agg.setdefault(pair, {
            "src_s1": 0, "src_s2": 0, "src_s3": 0,
            "ref_s1": 0, "ref_s2": 0, "ref_s3": 0,
            "s4_count": 0, "s4_src_chars": 0, "s4_ref_chars": 0,
            "s5_count": 0, "s5_src_chars": 0, "s5_ref_chars": 0,
            "doc_count": 0,
        })
        agg["src_s1"] += src["s1_chars"]
        agg["src_s2"] += src["s2_chars"]
        agg["src_s3"] += src["s3_chars"]
        agg["ref_s1"] += ref["s1_chars"]
        agg["ref_s2"] += ref["s2_chars"]
        agg["ref_s3"] += ref["s3_chars"]
        agg["s4_count"] += s4_count
        agg["s4_src_chars"] += s4_src_chars
        agg["s4_ref_chars"] += s4_ref_chars
        agg["s5_count"] += s5_count
        agg["s5_src_chars"] += s5_src_chars
        agg["s5_ref_chars"] += s5_ref_chars
        agg["doc_count"] += 1

    out_dir = PROJECT_ROOT / "outputs" / "analysis" / "z4_recovery_audit_20260729"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "by_document.json").write_text(
        json.dumps(by_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    ranking = []
    for pair, agg in by_lang_agg.items():
        src_recovery = agg["s5_src_chars"] / agg["src_s1"] if agg["src_s1"] else 0.0
        ref_recovery = agg["s5_ref_chars"] / agg["ref_s1"] if agg["ref_s1"] else 0.0
        combined = min(src_recovery, ref_recovery)
        ranking.append({
            "language_pair": pair,
            "doc_count": agg["doc_count"],
            "src_s1_chars": agg["src_s1"],
            "src_s2_chars": agg["src_s2"],
            "src_s3_chars": agg["src_s3"],
            "ref_s1_chars": agg["ref_s1"],
            "ref_s2_chars": agg["ref_s2"],
            "ref_s3_chars": agg["ref_s3"],
            "s4_count": agg["s4_count"],
            "s4_src_chars": agg["s4_src_chars"],
            "s4_ref_chars": agg["s4_ref_chars"],
            "s5_count": agg["s5_count"],
            "s5_src_chars": agg["s5_src_chars"],
            "s5_ref_chars": agg["s5_ref_chars"],
            "src_recovery_rate": src_recovery,
            "ref_recovery_rate": ref_recovery,
            "combined_recovery_rate": combined,
        })
    ranking.sort(key=lambda r: r["combined_recovery_rate"])

    (out_dir / "ranking.json").write_text(
        json.dumps(ranking, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(ranking, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
