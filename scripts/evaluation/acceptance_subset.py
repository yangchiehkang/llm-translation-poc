#!/usr/bin/env python3
"""验收子集口径：在严格全集之外，剔除有可核验事实依据的数据缺陷样本。

纪律：规则先定义后套用；每条剔除的理由必须是与分数无关的文本事实。
本脚本只读语料与打分结果，不修改语料。

规则清单
--------
R2   源文残句      去掉条款号后以小写功能词开头（上一条款的续行），或无句末标点且以功能词结尾
R2a  源文无句末标点 分两种事实，理由文案按实际情况生成：
                   (a) 源文在冒号处正常结束、列表项被切成独立 segment，而参考把整个列表
                       写在一段内 -> 粒度不可比（与 B 同族，不是截断）
                   (b) 源文既无句末标点也不以冒号结束，而参考是完整条款 -> 源文被截断
R2b  长度比异常    参考/源文字符比 > 0.75（全集中位约 0.31），中文更紧凑，比值反超说明
                   源文只覆盖了条款的一部分
R3   PDF 抽取噪声  命中已知页眉/水印字串，或含 PDF 抽取失败标记
R4   表格行        起始连续 >=3 个裸数字 token 后接列名且无句末标点（转数字一致率/格式
                   保持率专项评估，不进 DA 均值）
R5   下标塌陷      参考出现孤立单数字连排，是上下标被抽平甩到句尾的签名
B    参考过覆盖    参考句数 - 源文句数 >= 2，且源文自身完整（有句末标点、不以功能词结尾、
                   未被 R2/R2b 命中）
"""
from __future__ import annotations

import argparse
import json
import re
import statistics as st
from collections import Counter
from pathlib import Path

_SEC = re.compile(r"^\s*(?:\d{1,3}(?:\.\d{1,3})*\.?|[A-Z]\.)\s*")
_TERM = re.compile(r"[.。!?！？;；]\s*$")
_COLON_END = re.compile(r"[:：]\s*$")
_CONT = re.compile(r"^(?:or|and|but|nor|of|to|in|on|at|by|for|with|from|as|than|that|which|"
                   r"where|when|if|shall|may|is|are|was|were|be|been|the|a|an)\b", re.I)
_DANG = re.compile(r"\b(?:and|or|but|nor|of|to|in|on|at|by|for|with|from|as|than|that|which|"
                   r"where|when|if|the|a|an|is|are|was|were|be|been|shall|may|not|its|their|"
                   r"this|these)\s*$", re.I)
_WM = ["Applus IDIADA", "I.R.I.S. application", "Download from the",
       "shall not be held responsible", "ECE/TRANS/WP.29"]
_BRK = ["(cid:", "�"]
_BARE = re.compile(r"^\d+(?:\.\d+)*\.?$")
_SUB = re.compile(r"(?:(?<=\s)|(?<=（)|(?<=\()|(?<=、))\d(?:\s+\d){1,}")
_SENT_EN = re.compile(r"[.!?](?:\s|$)")
_SENT_ZH = re.compile(r"[。！？；]")

RATIO_CUT = 0.75
RATIO_MEDIAN_NOTE = "全集中位约 0.31"


def rules_for(row: dict) -> list[tuple[str, str]]:
    """返回 [(规则, 可核验理由)]；理由只陈述文本事实，不含分数。"""
    src, ref = row["source_text"], row["ref_text"]
    ns, nr = row["source_char_count"], row["ref_char_count"]
    out: list[tuple[str, str]] = []

    run = 0
    for tok in src.split():
        if _BARE.match(tok):
            run += 1
        else:
            break
    if run >= 3 and not _TERM.search(src):
        out.append(("R4", f"起始连续 {run} 个裸数字 token（{' '.join(src.split()[:run])}）后接列名，"
                          f"无句末标点；条款号被解析为表格首格数字 “{row.get('section_no')}”"))

    body = _SEC.sub("", src).strip()
    first = body.split()[0] if body.split() else ""
    src_complete = bool(_TERM.search(src)) and not _DANG.search(src)
    if _CONT.match(body) and first[:1].islower():
        out.append(("R2", f"去掉条款号后正文以小写功能词 “{first}” 开头，是上一条款的续行"))
    elif not _TERM.search(src) and _DANG.search(src):
        out.append(("R2", f"源文无句末标点，以功能词 “{src.strip().split()[-1]}” 结尾，句子被切断"))
    elif not _TERM.search(src) and _TERM.search(ref):
        if _COLON_END.search(src):
            # 冒号收尾：源文在此正常结束，列表项是独立 segment；参考把整个列表写在一段内。
            # 这是粒度不可比（与 B 同族），不是"源文被截断"。
            out.append(("R2a", f"源文在冒号处正常结束（止于 “…{src.strip()[-30:]}”），"
                               f"其列表项被切分为独立 segment；而参考把引导句与整个列表写在同一段内 "
                               f"→ 源文与参考的切分粒度不可比（与规则 B 同族，非源文截断）"))
        else:
            out.append(("R2a", f"源文无任何句末标点、也不以冒号结束（止于 “…{src.strip()[-28:]}”），"
                               f"而参考是以句号收尾的完整条款 → 源文被截断"))

    ratio = nr / max(ns, 1)
    if ratio > RATIO_CUT:
        out.append(("R2b", f"参考 {nr} 字 / 源文 {ns} 字，比值 {ratio:.2f} > {RATIO_CUT}"
                           f"（{RATIO_MEDIAN_NOTE}）；中文更紧凑，比值反超说明源文只覆盖条款的一部分"))

    for w in _WM:
        if w.lower() in src.lower():
            out.append(("R3", f"源文含页眉/水印字串 “{w}”")); break
        if w.lower() in ref.lower():
            out.append(("R3", f"参考含页眉/水印字串 “{w}”")); break
    for b in _BRK:
        if b in src or b in ref:
            out.append(("R3", f"含 PDF 抽取失败标记 “{b}”")); break

    m = _SUB.search(ref)
    if m:
        out.append(("R5", f"参考出现孤立单数字连排 “{m.group()}”，是上下标被抽平甩到句尾的签名"))

    ds = len(_SENT_ZH.findall(ref)) - len(_SENT_EN.findall(src))
    if ds >= 2 and src_complete and not any(r.startswith("R2") for r, _ in out):
        out.append(("B", f"参考 {len(_SENT_ZH.findall(ref))} 句 vs 源文 {len(_SENT_EN.findall(src))} 句，"
                         f"多 {ds} 句；源文自身以句末标点收尾且完整 → 参考覆盖了源文之外的后续条款"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--scores", default="", help="可选：sample_id -> score 的 JSONL，用于报均值")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    rows = [json.loads(x) for x in Path(args.corpus).read_text(encoding="utf-8").splitlines() if x.strip()]
    sc = {}
    if args.scores:
        for x in Path(args.scores).read_text(encoding="utf-8").splitlines():
            if x.strip():
                r = json.loads(x)
                sc[r["sample_id"]] = r.get("score", r.get("score_qwen36_40004"))

    excluded = {r["sample_id"]: (r, h) for r in rows for h in [rules_for(r)] if h}
    tbl = {s for s, (_, h) in excluded.items() if any(x == "R4" for x, _ in h)}
    keep = [r for r in rows if r["sample_id"] not in excluded]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "acceptance_subset_exclusions.jsonl").write_text("\n".join(
        json.dumps({
            "sample_id": s, "rules": sorted(x for x, _ in h), "reasons": [w for _, w in h],
            "bucket": "table_row_separate_metric" if s in tbl else "data_defect_excluded",
            "document_id": r["document_id"], "section_no": r.get("section_no"),
            "scope": r.get("scope", ""), "source_text": r["source_text"], "ref_text": r["ref_text"],
        }, ensure_ascii=False) for s, (r, h) in sorted(excluded.items())) + "\n", encoding="utf-8")

    summary = {
        "corpus": args.corpus, "full_n": len(rows),
        "excluded_n": len(excluded), "table_row_n": len(tbl), "subset_n": len(keep),
        "rule_hits": dict(Counter(x for _, h in excluded.values() for x, _ in h)),
        "subset_sample_ids": sorted(r["sample_id"] for r in keep),
    }
    if sc:
        allv = [sc[r["sample_id"]] for r in rows if r["sample_id"] in sc]
        kv = [sc[r["sample_id"]] for r in keep if r["sample_id"] in sc]
        summary["full_mean"] = st.mean(allv)
        summary["subset_mean"] = st.mean(kv)
    (out_dir / "acceptance_subset_ids.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "subset_sample_ids"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
