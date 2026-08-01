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
# R3 水印判据按"部件"匹配，不按完整字串——PDF 断行会把水印切开落进不同 segment，
# 只匹配 "Applus IDIADA" 这样的完整串会漏掉碎片。分两级：
#   _WM_STRONG  单独出现即成立：品牌名与 I.R.I.S. 的点分写法（含空格变体），法规正文不会出现
#   _WM_WEAK    需 >=2 个同现才成立：单独看是普通英文（"powered by an electric motor"
#               在电动车法规里完全合法），单个命中不足以定性
# 明确**不**匹配 I. / I / .I. 这类 1-2 字母碎片：689 条上审计过，这类模式命中的是
# "Part I:"、"Annex 9I"（DA 0.84/0.93/1.00）等合法正文，是误伤。断行若把水印削到只剩
# 单字母，本判据放弃该条——宁可漏，不可误。
_WM_STRONG = [
    re.compile(r"Applus", re.I),
    re.compile(r"IDIADA", re.I),
    re.compile(r"I\s*\.\s*R\s*\.\s*I\s*\.\s*S", re.I),   # I.R.I.S. 及其断行加空格变体
    re.compile(r"\bIRIS\b"),                              # ZH 侧出现的 "* IRIS注"
    re.compile(r"[Ff]or reference purposes only"),        # 水印固定尾句，正文不会出现
    re.compile(r"ECE/TRANS/WP\.29"),
    re.compile(r"shall not be held responsible", re.I),
]
_WM_WEAK = [
    re.compile(r"Download\s+from\b", re.I),
    re.compile(r"powered\s+by\b", re.I),
    re.compile(r"由\s*Applus"),
    re.compile(r"IDIADA\s*支持"),
    re.compile(r"应用程序\s*下载"),
    re.compile(r"仅供参考"),
]
_BRK = ["(cid:", "�"]


def _watermark_hit(text: str) -> str:
    """返回可核验的命中理由；无命中返回 ""。"""
    for rx in _WM_STRONG:
        m = rx.search(text)
        if m:
            return f"水印部件 “{m.group()}”"
    weak = [m.group() for rx in _WM_WEAK for m in [rx.search(text)] if m]
    if len(weak) >= 2:
        return "水印样板短语同现 " + "、".join(f"“{w}”" for w in weak)
    return ""
_BARE = re.compile(r"^\d+(?:\.\d+)*\.?$")
_SUB = re.compile(r"(?:(?<=\s)|(?<=（)|(?<=\()|(?<=、))\d(?:\s+\d){1,}")
# 两侧必须对称：中文侧不把 ； 算句末，英文侧也不算 ;；并排除条款号的点（"5.4.1." 不是句末）
_SENT_EN = re.compile(r"(?<!\d)[.!?](?=\s+[A-Z\"“(]|\s*$)")
_SENT_ZH = re.compile(r"[。！？]")

# 泰文没有句末标点这个书写惯例（2026-07-30，M6）：与 prepare_da_pairs.py 的
# has_complete_source_end 同一处修复的第二层。R2/R2a 判"源文是否完整收尾"用的
# _TERM 是拉丁/中文句末标点，泰文源文永远不匹配 —— 实测 20 条通过 prefilter 的
# 泰文样本被 R2a 全部误判成"源文被截断"，语料再次归零。
# 判据形状与拉丁侧一致（悬挂功能词），不为泰文单独放宽。
_THAI_RE = re.compile(r"[฀-๿]")
_THAI_DANG = re.compile(r"(?:และ|หรือ|ของ|ใน|ที่|เพื่อ|โดย|จาก|กับ|ตาม|ซึ่ง|แห่ง|เมื่อ|ถ้า|แต่)\s*$")


def _thai_dominant(text: str) -> bool:
    thai = len(_THAI_RE.findall(text))
    return thai > 0 and thai > len(re.findall(r"[A-Za-z一-鿿]", text))


def _src_terminated(src: str) -> bool:
    """源文是否"正常收尾"——按源文书写体系判，不按拉丁惯例一刀切。"""
    if _thai_dominant(src):
        return not _THAI_DANG.search(src)
    return bool(_TERM.search(src))


RATIO_CUT = 0.75
# 健康配对的参考/源文字符比中位（R100+R17 实测 0.293）。G2 用它推算参考的期望长度。
HEALTHY_RATIO = 0.29
G2_MIN_SOURCE = 1200      # 只在长源文上判，短句的比值波动大
G2_COVERAGE = 0.75        # 参考不足期望长度的 75% -> 参考没有随源文扩展
RATIO_MEDIAN_NOTE = "全集中位约 0.31"


def rules_for(row: dict, ref_followed_by_orphan: bool | None = None) -> list[tuple[str, str]]:
    """返回 [(规则, 可核验理由)]；理由只陈述文本事实，不含分数。

    ref_followed_by_orphan 由调用方从参考 PDF 的分段结果算出：参考段之后紧跟一个
    无条款号的孤儿段，说明该条款在参考侧被拆开、本条参考只拿到了第一段。
    """
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
    src_complete = _src_terminated(src) and not _DANG.search(src)
    if _CONT.match(body) and first[:1].islower():
        out.append(("R2", f"去掉条款号后正文以小写功能词 “{first}” 开头，是上一条款的续行"))
    elif not _src_terminated(src) and (_DANG.search(src) or _THAI_DANG.search(src)):
        out.append(("R2", f"源文无句末标点，以功能词 “{src.strip().split()[-1]}” 结尾，句子被切断"))
    elif not _src_terminated(src) and _TERM.search(ref):
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

    for side, text in (("源文", src), ("参考", ref)):
        why = _watermark_hit(text)
        if why:
            out.append(("R3", f"{side}含页眉/{why}")); break
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

    # G 粒度不对等：源文与参考的分段粒度不对等，参考侧仅覆盖源文的一部分。
    # 两个各自独立、都可核验的事实，命中其一即成立。
    if ref_followed_by_orphan:
        out.append(("G1", f"参考侧该条款被拆开：参考段之后紧跟一个无条款号的孤儿段，"
                          f"本条参考（{nr} 字）只拿到了第一段 → "
                          f"源文与参考分段粒度不对等，参考侧仅覆盖源文的一部分"))
    expected = HEALTHY_RATIO * ns
    if ns > G2_MIN_SOURCE and nr < expected * G2_COVERAGE:
        out.append(("G2", f"源文 {ns} 字，按健康配对比值 {HEALTHY_RATIO} 推算参考应约 {expected:.0f} 字，"
                          f"实际仅 {nr} 字（{nr/expected:.0%}）；参考长度未随源文扩展 → "
                          f"源文与参考分段粒度不对等，参考侧仅覆盖源文的一部分"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--scores", default="", help="可选：sample_id -> score 的 JSONL，用于报均值")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--raw-dir", default="", help="参考 PDF 所在目录；给了才能判 G1。")
    args = ap.parse_args()

    rows = [json.loads(x) for x in Path(args.corpus).read_text(encoding="utf-8").splitlines() if x.strip()]
    sc = {}
    if args.scores:
        for x in Path(args.scores).read_text(encoding="utf-8").splitlines():
            if x.strip():
                r = json.loads(x)
                sc[r["sample_id"]] = r.get("score", r.get("score_qwen36_40004"))

    # G1 需要参考侧的分段上下文：参考段之后是否紧跟无条款号的孤儿段。
    orphan_after: dict[str, bool] = {}
    if args.raw_dir:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from scripts.evaluation.prepare_da_pairs import parse_pdf_segments, MAX_SEGMENT_CHARS
        zh_idx: dict[str, tuple[list, dict]] = {}
        for doc in sorted({r["document_id"] for r in rows}):
            pdf = Path(args.raw_dir) / f"{doc}_zh.pdf"
            if not pdf.exists():
                continue
            segs = parse_pdf_segments(pdf, doc, "en-zh", "zh", min_chars=2,
                                      max_chars=MAX_SEGMENT_CHARS)[0]
            zh_idx[doc] = (segs, {s["text"]: i for i, s in enumerate(segs)})
        for r in rows:
            pair = zh_idx.get(r["document_id"])
            if not pair:
                continue
            segs, idx = pair
            i = idx.get(r["ref_text"])
            if i is not None and i + 1 < len(segs):
                orphan_after[r["sample_id"]] = not segs[i + 1].get("section_no")

    excluded = {r["sample_id"]: (r, h) for r in rows
                for h in [rules_for(r, orphan_after.get(r["sample_id"]))] if h}
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
