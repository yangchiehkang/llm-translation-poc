#!/usr/bin/env python3
"""Z1(ru) 报数：DA(段级) + QE + TCR，按长度带拆分，人工核对样本抽取。

纪律同 C1：缺文件抛错；术语库口径自检不过抛错；不接受"能跑通"作为正确性证据。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics as st
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

import sys
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.common.termbase import (  # noqa: E402
    hard_required_terms,
    load_termbase,
    match_terms,
    target_present,
)

EXPECT_TERMBASE_MD5 = "3b8221df26c70e1012cb367a6814f7fe"
EXPECT_N = 125
GATE = 0.95
BANDS = ["<=99", "100-199", "200-299", "300+"]


def band(n: int) -> str:
    return "<=99" if n < 100 else "100-199" if n < 200 else "200-299" if n < 300 else "300+"


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        raise FileNotFoundError(f"必需输入缺失：{p}")
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not rows:
        raise ValueError(f"输入为空：{p}")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--z1-dir", default="outputs/eval/ru_zh_z1_20260729")
    a = ap.parse_args()
    D = PROJECT_ROOT / a.z1_dir

    tb_path = PROJECT_ROOT / "termbase/auto_regulation_terms_v1.csv"
    md5 = hashlib.md5(tb_path.read_bytes()).hexdigest()
    if md5 != EXPECT_TERMBASE_MD5:
        raise ValueError(f"术语库 md5 漂移：{md5} != {EXPECT_TERMBASE_MD5}")
    terms = load_termbase(str(tb_path), source_lang="ru", target_lang="zh")
    print(f"[术语库] ru {len(terms)} 条，md5 {md5[:8]} 一致")

    da = {r["sample_id"]: r for r in read_jsonl(D / "z1_da_scores.jsonl")}
    qe = {r["sample_id"]: r for r in read_jsonl(D / "z1_qe_scores.jsonl")}
    hyp = {r["sample_id"]: r for r in read_jsonl(D / "z1_hyp.jsonl")}
    if len(da) != EXPECT_N or len(qe) != EXPECT_N or len(hyp) != EXPECT_N:
        raise ValueError(f"样本数不符：hyp={len(hyp)} da={len(da)} qe={len(qe)}，期望 {EXPECT_N}")
    if set(da) != set(qe) or set(da) != set(hyp):
        raise ValueError("三份文件的 sample_id 集合不一致")

    print("=" * 90)
    print("① TCR 门禁（术语级 < 95% 一律否决）")
    print("=" * 90)
    req = {sid: hard_required_terms(match_terms(hyp[sid]["source_text"], terms)) for sid in hyp}
    n_hard = sum(len(v) for v in req.values())
    tt = th = sn = sp = 0
    for sid, r in req.items():
        if not r:
            continue
        sn += 1
        ok = True
        for t in r:
            tt += 1
            if target_present(hyp[sid]["hypothesis"], t):
                th += 1
            else:
                ok = False
        sp += ok
    print(f"  硬术语实例总数 {n_hard}（{sn}/{EXPECT_N} 条含硬术语）")
    if tt:
        print(f"  术语级 {th}/{tt} = {th/tt:.2%}   样本级 {sp}/{sn} = {sp/sn:.2%}   "
              f"{'通过' if th/tt >= GATE else '**否决**'}")
    else:
        print("  本批次无硬术语命中，TCR 无法计算")

    print()
    print("=" * 90)
    print("② DA / QE 分档")
    print("=" * 90)
    da_scores = {sid: float(da[sid]["score"]) for sid in da}
    qe_scores = {sid: float(qe[sid]["score"]) for sid in qe}
    lens = {sid: len(hyp[sid]["source_text"]) for sid in hyp}

    def agg(scores):
        out = {}
        for b in BANDS:
            v = [s for i, s in scores.items() if band(lens[i]) == b]
            out[b] = (len(v), st.fmean(v) if v else None)
        allv = list(scores.values())
        out["全部"] = (len(allv), st.fmean(allv))
        return out

    da_agg, qe_agg = agg(da_scores), agg(qe_scores)
    print(f"{'口径':10s}{'n':>6s}{'DA':>10s}{'QE':>10s}")
    for b in BANDS + ["全部"]:
        n1, m1 = da_agg[b]
        n2, m2 = qe_agg[b]
        ms1 = f"{m1:10.4f}" if m1 is not None else f"{'—':>10s}"
        ms2 = f"{m2:10.4f}" if m2 is not None else f"{'—':>10s}"
        print(f"{b:10s}{n1:6d}{ms1}{ms2}")

    print()
    print(f"目标：DA >= 0.85（实测全部 {da_agg['全部'][1]:.4f}）"
          f"   {'达标' if da_agg['全部'][1] >= 0.85 else '未达标'}")

    out = {
        "n": EXPECT_N, "termbase_md5": md5,
        "tcr": {"term_level": th / tt if tt else None, "sample_level": sp / sn if sn else None,
                "hits": th, "total": tt, "hard_terms": n_hard},
        "da": {b: {"n": da_agg[b][0], "mean": da_agg[b][1]} for b in BANDS + ["全部"]},
        "qe": {b: {"n": qe_agg[b][0], "mean": qe_agg[b][1]} for b in BANDS + ["全部"]},
    }
    (D / "z1_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {a.z1_dir}/z1_result.json")


if __name__ == "__main__":
    main()
