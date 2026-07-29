#!/usr/bin/env python3
"""C1 少样本四臂 + 臂A + Y3 对照：TCR 门禁 + 段级/句级分档表。

**本脚本只在本地跑。** 服务器那份 `c1_analyze.py` 已作废，原因记在下面，
因为它犯的是本项目第四次同型错误——引用了冻结的旧副本却照常打印结论：

  1. `REPO=PROJECT_ROOT` 是**冻结副本**，其 `match_terms`
     缺 S3a span 抑制，硬术语数 1392 而非 1147（+21.4%）。用它算 TCR 会把
     四臂连同臂A 全部算成 ≈79.5% → 全判"否决"，且不报错。
  2. TCR 在 v2 保留集（627）上算，而已发布的 96.51% 是在**全集 689** 上算的。
  3. `try/except FileNotFoundError: pass` 让缺失的分数文件静默消失，
     表照常打印，只是少几行——看上去像"C1 没效果"。

所以这里的纪律是：**缺文件抛错；口径自检不过抛错。**
下面三个常量是护栏，它们对不上就说明代码或数据漂了，宁可炸也不出数。
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.termbase import (  # noqa: E402
    hard_required_terms,
    load_termbase,
    match_terms,
    target_present,
)

# ---- 口径护栏：与 outputs/eval/en_zh_689_v2_20260728/README.md 已发布数一致 ----
EXPECT_TERMBASE_MD5 = "3b8221df26c70e1012cb367a6814f7fe"   # T4 版术语库
EXPECT_HARD_TERMS = 1147          # 全集 689 上的硬术语实例数（当前 match_terms）
EXPECT_ARMA_TCR = (1107, 1147)    # 臂A 术语级 96.51%
EXPECT_ARMA_SAMPLE = (506, 545)   # 臂A 样本级 92.84%

V2_RULES = {"R2", "R2a", "R2b", "G1", "G2", "R3", "R5", "β"}
BANDS = ["<=99", "100-199", "200-299", "300+"]
ARMS = ["random_k2", "random_k5", "curated_k2", "curated_k5"]
GATE = 0.95


def band(n: int) -> str:
    return "<=99" if n < 100 else "100-199" if n < 200 else "200-299" if n < 300 else "300+"


def read_jsonl(p: Path) -> list[dict]:
    """缺文件抛错。绝不 try/except pass——那是静默给出错误结论的入口。"""
    if not p.exists():
        raise FileNotFoundError(
            f"必需输入缺失：{p}\n"
            f"（若 C1 打分尚未跑完，先跑完再来；不要让它静默缺席）"
        )
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not rows:
        raise ValueError(f"输入为空：{p}")
    return rows


def by_id(rows: list[dict]) -> dict[str, dict]:
    return {r["sample_id"]: r for r in rows}


def tcr(hyp_by_id: dict[str, str], req_by_id: dict[str, list], ids: list[str]) -> tuple:
    """术语级 / 样本级 TCR。在**全集 689** 上算，与已发布口径一致。"""
    tt = th = sn = sp = 0
    for i in ids:
        req = req_by_id[i]
        if not req:
            continue
        sn += 1
        ok = True
        for t in req:
            tt += 1
            if target_present(hyp_by_id[i], t):
                th += 1
            else:
                ok = False
        sp += ok
    return th, tt, sp, sn


def agg(scores: dict[str, float], lens: dict[str, int]) -> dict:
    out, le = {}, []
    for b in BANDS:
        v = [s for i, s in scores.items() if band(lens[i]) == b]
        out[b] = {"n": len(v), "da": st.fmean(v) if v else None}
        if b in ("<=99", "100-199"):
            le += v
    allv = list(scores.values())
    out["<=199"] = {"n": len(le), "da": st.fmean(le) if le else None}
    out["全部"] = {"n": len(allv), "da": st.fmean(allv) if allv else None}
    return out


def table(title: str, per_sys: dict[str, dict], order: list[str], base: str) -> None:
    print("=" * 96)
    print(title)
    print("=" * 96)
    cols = BANDS + ["<=199", "全部"]
    print(f"{'系统':16s}" + "".join(f"{c:>12s}" for c in cols))
    for nm in order:
        a = per_sys[nm]
        row = f"{nm:16s}"
        for c in cols:
            d = a[c]
            row += f"{d['da']:12.4f}" if d["da"] is not None else f"{'—':>12s}"
        print(row)
    print(f"{'(n)':16s}" + "".join(f"{per_sys[base][c]['n']:12d}" for c in cols))
    print()
    print(f"相对 {base} 的增益：")
    for nm in order:
        if nm == base:
            continue
        row = f"  {nm:14s}"
        for c in cols:
            d, b = per_sys[nm][c], per_sys[base][c]
            row += f"{d['da']-b['da']:+12.4f}" if (d["da"] is not None and b["da"] is not None) else f"{'—':>12s}"
        print(row)
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--c1-dir", default="outputs/eval/en_zh_689_c1_20260729")
    ap.add_argument("--out", default="outputs/eval/en_zh_689_c1_20260729/c1_result.json")
    a = ap.parse_args()

    R = PROJECT_ROOT
    C1 = R / a.c1_dir

    # ---- 术语库口径自检 ----
    tb_path = R / "termbase/auto_regulation_terms_v1.csv"
    import hashlib
    md5 = hashlib.md5(tb_path.read_bytes()).hexdigest()
    if md5 != EXPECT_TERMBASE_MD5:
        raise ValueError(f"术语库 md5 漂移：{md5} != {EXPECT_TERMBASE_MD5}（期望 T4 版）")
    terms = load_termbase(str(tb_path), source_lang="en", target_lang="zh")

    # ---- 剔除账本 / 臂A / Y3 ----
    led = {}
    for r in read_jsonl(R / "outputs/eval/en_zh_689_20260727/acceptance_subset_exclusions.jsonl"):
        led[r["sample_id"]] = set(r.get("rules", []))
    A = by_id(read_jsonl(R / "outputs/eval/en_zh_689_v2_20260728/armA_scores.jsonl"))
    Y = by_id(read_jsonl(R / "outputs/eval/en_zh_689_y3_20260729/y3_da_scores.jsonl"))
    ALL = sorted(A)
    KEEP = {i for i in ALL if not (led.get(i, set()) & V2_RULES)}
    if len(ALL) != 689 or len(KEEP) != 627:
        raise ValueError(f"样本集漂移：全集 {len(ALL)}（期望 689）/ v2 保留 {len(KEEP)}（期望 627）")

    # ---- C1 四臂 ----
    seg = {arm: by_id(read_jsonl(C1 / f"c1_{arm}_scores.jsonl")) for arm in ARMS}
    for arm, d in seg.items():
        if set(d) != set(ALL):
            raise ValueError(f"{arm} 样本集与臂A不一致")

    # ---- TCR 口径自检 ----
    req = {i: hard_required_terms(match_terms(A[i]["source_text"], terms)) for i in ALL}
    n_hard = sum(len(v) for v in req.values())
    if n_hard != EXPECT_HARD_TERMS:
        raise ValueError(
            f"硬术语实例数 {n_hard} != {EXPECT_HARD_TERMS}。"
            f"这正是冻结副本的症状（旧 match_terms 无 S3a span 抑制会给出 1392）。"
            f"不出数。"
        )

    systems = {
        "臂A(零样本)": {i: A[i]["hypothesis_translation"] for i in ALL},
        "random_k2": {i: seg["random_k2"][i]["hypothesis_translation"] for i in ALL},
        "random_k5": {i: seg["random_k5"][i]["hypothesis_translation"] for i in ALL},
        "curated_k2": {i: seg["curated_k2"][i]["hypothesis_translation"] for i in ALL},
        "curated_k5": {i: seg["curated_k5"][i]["hypothesis_translation"] for i in ALL},
        "Y3重排序": {i: Y[i]["hypothesis_translation"] for i in ALL},
    }
    ORDER = list(systems)

    print("=" * 96)
    print(f"① TCR 门禁（术语级 < {GATE:.0%} 一律否决）   全集 689，术语库 T4 {md5[:8]}")
    print("=" * 96)
    gate = {}
    for nm, hyp in systems.items():
        th, tt, sp, sn = tcr(hyp, req, ALL)
        gate[nm] = {"term_level": th / tt, "sample_level": sp / sn,
                    "hits": th, "total": tt, "ok": th / tt >= GATE}
        if nm == "臂A(零样本)":
            if (th, tt) != EXPECT_ARMA_TCR or (sp, sn) != EXPECT_ARMA_SAMPLE:
                raise ValueError(
                    f"臂A TCR 复现失败：术语级 {th}/{tt}（期望 {EXPECT_ARMA_TCR}）"
                    f" 样本级 {sp}/{sn}（期望 {EXPECT_ARMA_SAMPLE}）。不出数。"
                )
        print(f"  {nm:16s} 术语级 {th:5d}/{tt} = {th/tt:7.2%}   样本级 {sp:4d}/{sn} = {sp/sn:7.2%}   "
              f"{'通过' if th/tt >= GATE else '**否决**'}")
    print()

    # ---- 段级 ----
    seg_len = {i: len(A[i]["source_text"]) for i in KEEP}
    seg_tbl = {
        "臂A(零样本)": agg({i: float(A[i]["score"]) for i in KEEP}, seg_len),
        "Y3重排序": agg({i: float(Y[i]["score"]) for i in KEEP}, seg_len),
    }
    for arm in ARMS:
        seg_tbl[arm] = agg({i: float(seg[arm][i]["score"]) for i in KEEP}, seg_len)
    table("② 段级 DA 分档（v2 保留集 627）", seg_tbl, ORDER, "臂A(零样本)")

    # ---- 句级 ----
    def sent(path: Path) -> dict:
        sc, ln = {}, {}
        for r in read_jsonl(path):
            parent = r.get("parent_id") or r["sample_id"].split("#")[0]
            if parent not in KEEP:
                continue
            sc[r["sample_id"]] = float(r["score"])
            ln[r["sample_id"]] = len(r["source_text"])
        return agg(sc, ln)

    sent_tbl = {
        "臂A(零样本)": sent(R / "outputs/eval/en_zh_689_sentence_20260728/sent_scores.jsonl"),
        "Y3重排序": sent(R / "outputs/eval/en_zh_689_y3_20260729/y3_sent_scores.jsonl"),
    }
    for arm in ARMS:
        sent_tbl[arm] = sent(C1 / f"c1_{arm}_sent_scores.jsonl")
    table("③ 句级 DA 分档（v2 保留集内已对齐句；各系统句数不同因切分随译文而变）",
          sent_tbl, ORDER, "臂A(零样本)")
    print("句数（各系统自己的分母）：")
    for nm in ORDER:
        print(f"  {nm:16s} " + "  ".join(f"{c} {sent_tbl[nm][c]['n']}" for c in BANDS + ["<=199", "全部"]))
    print()

    # ---- 结论判据 ----
    print("=" * 96)
    print("④ 判据结算")
    print("=" * 96)
    base_seg = seg_tbl["臂A(零样本)"]["全部"]["da"]
    base_sent = sent_tbl["臂A(零样本)"]["全部"]["da"]
    for arm in ARMS:
        g = gate[arm]
        d_seg = seg_tbl[arm]["全部"]["da"] - base_seg
        d_sent = sent_tbl[arm]["全部"]["da"] - base_sent
        verdict = ("**TCR 否决**" if not g["ok"]
                   else "正收益" if (d_seg > 0 and d_sent > 0)
                   else "无收益/负收益")
        print(f"  {arm:14s} TCR {g['term_level']:7.2%} {'通过' if g['ok'] else '否决'}   "
              f"段级 {d_seg:+.4f}   句级 {d_sent:+.4f}   -> {verdict}")
    print()
    print("  注：随机臂的少样本示例取自**评测集内其它行的参考译文**（c1_gen.py 的 pool 即评测集），")
    print("      属 leave-one-out 式泄漏，其增益系统性上偏；精选臂取自 R016 训练对，对评测集零泄漏。")

    out = {
        "tcr_gate": gate,
        "segment_level": seg_tbl,
        "sentence_level": sent_tbl,
        "guards": {"termbase_md5": md5, "hard_terms": n_hard,
                   "armA_tcr": list(EXPECT_ARMA_TCR), "n_all": len(ALL), "n_keep": len(KEEP)},
        "leakage_note": "random 臂示例取自评测集参考译文（leave-one-out 泄漏）；curated 臂取自 R016 训练对，零泄漏",
    }
    Path(R / a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(R / a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
