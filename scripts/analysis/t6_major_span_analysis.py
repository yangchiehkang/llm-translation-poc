#!/usr/bin/env python3
"""T6 — major error span 分析（方法同 D2-a，但先剥噪声再报覆盖率）。

之前只分析过 critical（133 个）。major 约 639 个，是 critical 的近 5 倍，DA 主要由它决定。

D2-a 踩过的坑，这里按顺序防住
------------------------------
D2-a 没先剥已知噪声类就报覆盖率，差点得出错误结论。本脚本**强制**先分类剥离：
  水印类   Applus / IDIADA / I.R.I.S / Download from / reference purposes only
  罗马数字 单独的 I / II / III / IV … 编号
  PDF 抽取 (cid: / U+FFFD / 孤立单数字连排
剥完之后才统计 Top N 与覆盖率，两套数（剥前/剥后）都报，不允许只报一个。

输入
----
带 error_spans 的打分结果 JSONL。span 由 scripts/evaluation/run_xcomet.py 落盘
（`error_spans` 字段，含 severity / text / start / end）。
**若输入不含 span，本脚本直接报错退出，不做任何近似替代。**
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.common.termbase import load_termbase, match_terms  # noqa: E402

T5_LEDGER = "outputs/analysis/t5_termbase_vs_ref_20260728/t5_ledger.jsonl"

# ---- 已知噪声类：先剥离，再报覆盖率（D2-a 的教训）----
NOISE = {
    # span 取自**译文**，模型会把水印一起翻成中文，所以中英两侧的写法都要收。
    # 只收英文侧会漏掉「下载。仅供参考」「应用程序下载。仅供参考」这类纯中文残片。
    "watermark": re.compile(
        r"Applus|IDIADA|I\s*\.\s*R\s*\.\s*I\s*\.\s*S|\bIRIS\b|Download\s+from|"
        r"powered\s+by|reference\s+purposes\s+only|ECE/TRANS/WP\.29|"
        r"仅供参考|应用程序下载|由\s*Applus|IDIADA\s*支持", re.I),
    "roman_numeral": re.compile(r"^\s*\(?[IVXLC]{1,6}\)?[.、)]?\s*$"),
    "pdf_broken": re.compile(r"\(cid:|�"),
    "digit_run": re.compile(r"^\s*\d(?:\s+\d){1,}\s*$"),
    "punct_only": re.compile(r"^[\W_]+$", re.U),
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").strip()
    return re.sub(r"\s+", " ", s)


def noise_class(text: str) -> str:
    for name, rx in NOISE.items():
        if rx.search(text):
            return name
    return ""


def band(n: int) -> str:
    return "<100" if n < 100 else "100-199" if n < 200 else "200-299" if n < 300 else "300+"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", required=True, help="含 error_spans 的打分 JSONL")
    ap.add_argument("--corpus", default="outputs/eval/en_zh_689_20260727/full_results.jsonl",
                    help="用于长度带与源文（映射回英文术语）")
    ap.add_argument("--termbase", default="termbase/auto_regulation_terms_v1.csv")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--out-dir", default="outputs/analysis/t6_major_span_20260728")
    args = ap.parse_args()

    rows = [json.loads(x) for x in Path(args.scores).read_text(encoding="utf-8").splitlines() if x.strip()]
    # error_spans 有两种落盘形态：
    #   list  —— 修好后的 run_xcomet.py 直接写 JSON 数组
    #   str   —— 打分机上早先的脚本把 Python 对象 repr 成字符串塞进字段
    # 两种都要吃，否则 t4_scores.jsonl 这份现成的 span 用不上。
    import ast
    for r in rows:
        es = r.get("error_spans")
        if isinstance(es, str):
            try:
                r["error_spans"] = ast.literal_eval(es) if es.strip() else []
            except (ValueError, SyntaxError):
                r["error_spans"] = []
    with_spans = [r for r in rows if r.get("error_spans")]
    if not with_spans:
        sys.exit(
            "错误：输入不含 error_spans，T6 无法进行。\n"
            f"  文件：{args.scores}（{len(rows)} 行，0 行带 span）\n"
            "  原因：run_xcomet.py 此前只落盘 .scores，XCOMET 的 error span 被丢弃。\n"
            "  解法：该脚本已修好（success_result 增加 error_spans 字段），"
            "在打分机上重跑一次 XCOMET-XXL 即可产出。span 是模型自带产物，不增加计算成本。\n"
            "  本脚本不做任何近似替代——用启发式伪造 span 会得出无法追责的结论。")

    corpus = {}
    if Path(args.corpus).exists():
        for x in Path(args.corpus).read_text(encoding="utf-8").splitlines():
            if x.strip():
                r = json.loads(x)
                corpus[r["sample_id"]] = r
    terms = load_termbase(args.termbase, "en", "zh")

    # ---- 1. 全量收集 ----
    spans = []
    for r in rows:
        for s in r.get("error_spans") or []:
            sev = str(s.get("severity", "")).lower()
            spans.append({"sample_id": r["sample_id"], "severity": sev,
                          "text": norm(s.get("text", "")),
                          "start": s.get("start"), "end": s.get("end")})
    by_sev = Counter(s["severity"] for s in spans)
    major = [s for s in spans if s["severity"] == "major"]
    print(f"样本 {len(rows)} 条，其中 {len(with_spans)} 条带 span")
    print(f"span 合计 {len(spans)}：{dict(by_sev)}")
    print(f"major {len(major)} 个\n")

    # ---- 2. 先剥噪声 ----
    tagged = [(s, noise_class(s["text"])) for s in major]
    noise_hits = Counter(c for _, c in tagged if c)
    clean = [s for s, c in tagged if not c]
    print("=" * 78)
    print("① 噪声剥离（先剥再统计——D2-a 就是漏了这一步）")
    print("=" * 78)
    for k, v in noise_hits.most_common():
        print(f"   {k:16s} {v:5d}  ({v/len(major):5.1%})")
    print(f"   {'剥除合计':16s} {len(major)-len(clean):5d}  ({1-len(clean)/len(major):5.1%})")
    print(f"   {'剩余 major':16s} {len(clean):5d}")

    # ---- 3. Top N（剥前 / 剥后都报）----
    def topn(items, n):
        c = Counter(s["text"] for s in items if s["text"])
        return c.most_common(n), sum(c.values())

    raw_top, raw_tot = topn(major, args.top)
    top, tot = topn(clean, args.top)
    print()
    print("=" * 78)
    print(f"② Top {args.top}（剥噪声后）")
    print("=" * 78)
    print(f"{'#':>3s} {'span':38s} {'次数':>5s} {'累计占比':>8s} {'源端术语':22s} {'在库':>4s}")
    cum = 0
    top_rows = []
    for i, (t, c) in enumerate(top, 1):
        cum += c
        sids = [s["sample_id"] for s in clean if s["text"] == t]
        srcs = " ".join(corpus[x]["source_text"] for x in sids[:6] if x in corpus)
        cand = [m["source_term"] for m in match_terms(srcs, terms)] if srcs else []
        in_tb = "是" if cand else "否"
        top_rows.append({"rank": i, "span": t, "count": c, "cum_share": cum / max(tot, 1),
                         "src_terms": cand[:5], "in_termbase": bool(cand),
                         "sample_ids": sids[:10]})
        print(f"{i:3d} {t[:37]:38s} {c:5d} {cum/max(tot,1):8.1%} "
              f"{','.join(cand[:2])[:21]:22s} {in_tb:>4s}")

    # ---- 4. 覆盖率门槛数，按长度带 ----
    print()
    print("=" * 78)
    print(f"③ 覆盖率门槛数：Top {args.top} 覆盖剩余 major 的多少")
    print("=" * 78)
    print(f"   剥噪声前：Top {args.top} / 全部 major = {sum(c for _, c in raw_top)}/{raw_tot} "
          f"= {sum(c for _, c in raw_top)/max(raw_tot,1):.1%}")
    print(f"   剥噪声后：Top {args.top} / 剩余 major = {cum}/{tot} = {cum/max(tot,1):.1%}   <- 门槛数")
    band_cov = {}
    print(f"\n{'长度带':>10s} {'major':>7s} {'TopN命中':>9s} {'覆盖率':>8s}")
    topset = {t for t, _ in top}
    for b in ["<100", "100-199", "200-299", "300+"]:
        sub = [s for s in clean if s["sample_id"] in corpus
               and band(corpus[s["sample_id"]]["source_char_count"]) == b]
        hit = sum(1 for s in sub if s["text"] in topset)
        band_cov[b] = {"major": len(sub), "top_hit": hit,
                       "coverage": hit / len(sub) if sub else 0.0}
        print(f"{b:>10s} {len(sub):7d} {hit:9d} {hit/len(sub) if sub else 0:8.1%}")

    # ---- 5. 与 T5 相悖清单交叉 ----
    print()
    print("=" * 78)
    print("④ 与 T5【相悖】清单交叉——两个独立方法是否指向同一批术语")
    print("=" * 78)
    cross = {"available": False}
    if Path(T5_LEDGER).exists():
        t5 = [json.loads(x) for x in Path(T5_LEDGER).read_text(encoding="utf-8").splitlines() if x.strip()]
        conf = {e["source_term"]: e for e in t5 if e["class"] in ("相悖", "空格差异")}
        # 一个 major span 若其样本源文含某相悖术语，且 span 文本含该术语的现译法，则判为落在该术语上
        # span 多是 1-5 字的碎片：「可充电」是 REESS 目标译法「可充电储能系统」的片段，
        # 「外壳混合」把目标译法「外壳」包在里面。只判 target in span 会两头都漏。
        # 故用**双向包含**，并要求 >=2 字（单字如「外」「腔」噪声太大）。
        # 这与 T5 里踩过的片段坑是同一类，不能在这里再踩一次。
        hit_by_term: dict[str, int] = defaultdict(int)
        n_on_conf = 0
        for s in clean:
            r = corpus.get(s["sample_id"])
            if not r:
                continue
            txt = s["text"]
            if len(txt) < 2:
                continue
            for st, e in conf.items():
                tgt = e["target_term"]
                if not tgt or st.lower() not in r["source_text"].lower():
                    continue
                if tgt in txt or (len(txt) >= 2 and txt in tgt):
                    hit_by_term[st] += 1
                    n_on_conf += 1
                    break
        print(f"   落在 T5 相悖术语上的 major span：{n_on_conf} / {len(clean)} "
              f"= {n_on_conf/max(len(clean),1):.1%}")
        for st, c in sorted(hit_by_term.items(), key=lambda kv: -kv[1]):
            e = conf[st]
            print(f"      {st:34s} 现「{e['target_term']}」 参考「{e['ref_dominant']}」 "
                  f"major span {c:3d}  T5推错 {e['pushed_wrong']:.0f}")
        cross = {"available": True, "spans_on_conflict_terms": n_on_conf,
                 "clean_major": len(clean),
                 "share": n_on_conf / max(len(clean), 1),
                 "by_term": dict(hit_by_term)}
        print("\n   判读：占比高 -> T5 的改动有双重证据；占比低 -> major 的成因另有其他，需重想。")
    else:
        print(f"   T5 台账不存在（{T5_LEDGER}），跳过。")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "t6_major_spans.json").write_text(json.dumps({
        "scores_file": args.scores, "n_rows": len(rows), "n_rows_with_spans": len(with_spans),
        "span_totals": dict(by_sev), "major_total": len(major),
        "noise_stripped": dict(noise_hits), "major_clean": len(clean),
        "top_n": args.top, "top": top_rows,
        "coverage_before_strip": sum(c for _, c in raw_top) / max(raw_tot, 1),
        "coverage_after_strip": cum / max(tot, 1),
        "coverage_by_band": band_cov, "t5_cross": cross,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out/'t6_major_spans.json'}")


if __name__ == "__main__":
    main()
