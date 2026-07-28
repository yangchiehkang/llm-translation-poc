#!/usr/bin/env python3
"""T5 — 全量硬术语对照参考语料（补 T2 的盲区）。

问题：enclosure -> 外壳 命中率 91.7%，TCR 上完全健康，但参考写「密闭室」。
这类术语**在每一个实例上把译文推离参考**。T2 只审了正在失败的那几条，
剩下的硬术语实例从未对照过参考。

方法（与 T2 一致，只换一批术语）：对语料里出现的**每一条**硬术语，统计参考语料
在对应位置的实际中文写法与次数，与 target_term 比对，分三类。

参考侧写法怎么找出来（源文只有英文，参考只有中文，没有词对齐）
--------------------------------------------------------------
用共现 + 出现次数吻合度做穷人版短语对齐：
  A = 源文含该术语的样本集合（**按 ref_text 去重**），B = 其余样本
  对参考里的每个 n-gram g（n=2..10，中文与拉丁串都收），算
      recall    = |{a in A : g in ref(a)}| / |A|
      precision = |{a in A : g in ref(a)}| / |{所有含 g 的样本}|
      countfit  = 逐样本比较「术语在源文出现几次」与「g 在参考出现几次」的吻合度

三个坑，都是实测踩出来的，必须防：

1. **拉丁串不能漏**：参考直接用 `REESS` / `SOC` / `IPXXB` 拉丁缩写。只抽中文 n-gram
   会把 REESS（125 实例，最大的一块）误判成"无法验证"。n-gram 因此在中文与拉丁
   混合的"内容字符"序列上抽。

2. **近重复条款会毒化共现**：B1 查明 R100 把验收判据整段复读 6 次。venting 的 7 个
   实例里多条是同一段文字，于是"不需对试验装置的任何"这种样板短语拿到 recall=1.0、
   precision=1.0，排在真正的译法「通风」前面。**按 ref_text 去重**后才统计。

3. **片段不能冒充译法**：`流保护` 是 `过流保护` 的子串、`外露` 是 `外露导电部件` 的子串。
   光看 recall 会选中片段。用 countfit 惩罚（片段的出现次数与术语次数对不上），
   并在同 recall 时取最长。

这套判据只用**参考语料**，不看模型输出，也不看任何分数。
命中率与"被推错实例数"是事后附加的排序列，不参与分类。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.common.termbase import (  # noqa: E402
    load_termbase, match_terms, hard_required_terms, target_present,
)

RESULTS = "outputs/eval/en_zh_689_20260727/full_results.jsonl"
TERMBASE = "termbase/auto_regulation_terms_v1.csv"
OUT = Path("outputs/analysis/t5_termbase_vs_ref_20260728")

# 内容字符串：中文连续段，或拉丁/数字连续段（参考直接用 REESS / SOC / IPXXB）
RUN = re.compile(r"[一-鿿]+|[A-Za-z][A-Za-z0-9]*")
NMIN, NMAX = 2, 10
MIN_RECALL = 0.30          # 候选写法至少要在 30% 的（去重后）实例参考里出现
MIN_PRECISION = 0.50       # 且含该写法的样本里至少一半确实含该术语
MIN_COUNTFIT = 0.40        # 出现次数吻合度下限，用来打掉样板短语与片段
MIN_INSTANCES = 3          # 实例数 <3 的术语统计不可靠，单列


# 语法性汉字：术语写法里基本不会出现。候选串含之则不可信（拉丁串豁免）。
# 刻意不放 内/外/上/下/前/后 —— 外壳、密闭室内部这类合法术语要用到。
FUNC = set("的地得而则若及以其该本由从至于见应需可将被把等这那了是在和与或对按使之")


def runs(text: str) -> list[str]:
    return RUN.findall(text)


def trim(g: str) -> str:
    """削掉首尾的语法字：认证标识应 -> 认证标识，动力蓄电池的 -> 动力蓄电池。"""
    while g and g[0] in FUNC:
        g = g[1:]
    while g and g[-1] in FUNC:
        g = g[:-1]
    return g


def term_like(g: str) -> bool:
    """像不像一条术语写法。不像的一律不当作『参考实际写法』断言出去。"""
    if g.isascii():
        return len(g) >= 2
    return 2 <= len(g) <= 10 and not (set(g) & FUNC)


def ngram_counts(text: str) -> Counter[str]:
    """n-gram -> 在该文本里出现的次数。中文按字切，拉丁串整体作为一个 token。"""
    c: Counter[str] = Counter()
    for run in runs(text):
        if run[0].isascii():          # 拉丁串不切分
            c[run] += 1
            continue
        for n in range(NMIN, NMAX + 1):
            for i in range(len(run) - n + 1):
                c[run[i:i + n]] += 1
    return c


# ---------------------------------------------------------------------------
# 人工裁定表：自动候选跑完后，逐条对照参考原文核过。只改"参考实际写法"与分类，
# 不改实例数/命中率。每条带参考原文引证，可复核。依据只用参考语料。
# verdict: conflict=相悖 / unverifiable=无法验证 / spacing=空格差异 / agree=一致
# ---------------------------------------------------------------------------
ADJUDICATION: dict[str, dict] = {
    "venting": {
        "verdict": "conflict", "ref_form": "通风", "ref_count": 7,
        "why": "自动候选选中样板短语。参考 6.2.2.1 “(c) 通风（对于开放式动力蓄电池以外的"
               "REESS）”，7 条实例参考一律写「通风」，现译法「排气」在参考中 0 次。",
    },
    "energy absorption test": {
        "verdict": "conflict", "ref_form": "能量耗散试验 / 吸能试验", "ref_count": 2,
        "why": "参考两种写法并存：5.2.3「通过能量耗散试验」、5.5.2「通过吸能试验」。"
               "现译法「能量吸收试验」在参考中 0 次。因两写法并存，宜加 target_alias 而非改 target。",
    },
    "3-D H machine": {
        "verdict": "spacing", "ref_form": "三维 H 点装置（带空格）", "ref_count": 3,
        "why": "参考 2.24「“三维 H 点装置”」、5.2「三维 H 点装置测量」——译法与我们**相同**，"
               "差别只在拉丁字母两侧的空格。现 target「三维H点装置」无空格，逐字匹配失败。"
               "这不是译法冲突，是空格规范问题，改法与相悖类不同。",
    },
    "traction battery": {
        "verdict": "conflict", "ref_form": "动力蓄电池", "ref_count": 2,
        "why": "参考 5.2.2「开放式动力蓄电池」、5.「动力蓄电池的放电」；另有 6.12.3"
               "「牵引用蓄电池」、5.1.1「牵引电池」各 1 次。主流为「动力蓄电池」，"
               "现译法「牵引蓄电池」在参考中 0 次。",
    },
    "type approval": {
        "verdict": "unverifiable", "ref_form": "", "ref_count": 0,
        "why": "自动候选「认证管理机构」实为 type approval **authority** 的译法，不是本词条。"
               "参考写「车型认证」「批准此认证」，随语境变形，无稳定独立写法。降级为无法验证。",
    },
    "IPXXB": {
        "verdict": "conflict", "ref_form": "IPXXB（裸写）", "ref_count": 3,
        "why": "参考 5.1.1.2「防护等级应满足IPXXB」、2.39「试验指（IPXXB）」用裸 IPXXB；"
               "仅 2.20 写「IPXXB防护等级」。现 target「IPXXB防护等级」过长，"
               "参考主流是裸写 → 宜把 target 放宽为 IPXXB。",
    },
    "Rechargeable Electrical Energy Storage System": {
        "verdict": "conflict", "ref_form": "REESS", "ref_count": 5,
        "why": "与 REESS 词条同一事实：参考全文用拉丁缩写 REESS，不用「可充电储能系统」。",
    },
    "exposed conductive part": {
        "verdict": "conflict", "ref_form": "外露导电部件", "ref_count": 2,
        "why": "参考 2.20「“外露导电部件”」、2.26「与外露导电部件的接触」；"
               "5.1.2.1 另写「外露的导体部件」。现译法「外露可导电部分」在参考中 0 次。",
    },
    "UN Regulation": {
        "verdict": "unverifiable", "ref_form": "", "ref_count": 0,
        "why": "参考把编号插在词中间：「联合国第 94 号法规」「联合国第 21 号法规」。"
               "这是构式差异不是词条差异，无法用固定字串表达，术语库层面改不了。",
    },
    "vibration test": {
        "verdict": "unverifiable", "ref_form": "", "ref_count": 0,
        "why": "参考只出现「振动环境」「振动机器平台」，未出现独立的试验名写法；"
               "6.12.3 的试验清单在参考里未展开。证据不足以断言。",
    },
    "shall not": {
        "verdict": "unverifiable", "ref_form": "", "ref_count": 0,
        "why": "情态词随语境变形：「不视为」「不适用」「不得超过」「不应」。"
               "没有单一固定写法可对照，且 target_aliases 已覆盖主要变体。",
    },
}


def main() -> None:
    rows = [json.loads(x) for x in Path(RESULTS).read_text(encoding="utf-8").splitlines() if x.strip()]
    terms = load_termbase(TERMBASE, "en", "zh")

    # ---- 1. 每条硬术语在语料里的实例（口径与 TCR 分母一致：match_terms 后取 hard）----
    inst: dict[str, list[int]] = defaultdict(list)
    tmeta: dict[str, dict] = {}
    for i, r in enumerate(rows):
        for t in hard_required_terms(match_terms(r["source_text"], terms)):
            key = t["source_term"]
            inst[key].append(i)
            tmeta.setdefault(key, t)
    total_inst = sum(len(v) for v in inst.values())
    print(f"语料 {len(rows)} 条；硬术语 {len(inst)} 条，实例合计 {total_inst}"
          f"（与术语级 TCR 分母同口径）\n")

    # ---- 2. 参考侧 n-gram 倒排（含出现次数）----
    ref_ng = [ngram_counts(r["ref_text"]) for r in rows]
    df: Counter[str] = Counter()
    for c in ref_ng:
        df.update(c.keys())

    def src_count(i: int, term: dict) -> int:
        """术语在该条源文里出现几次（含源端 alias）。"""
        txt = rows[i]["source_text"].lower()
        forms = [term["source_term"]] + list(term.get("aliases") or [])
        return max(1, sum(txt.count(f.lower()) for f in forms if f))

    def candidates(idxs: list[int], term: dict) -> list[dict]:
        target = str(term.get("target_term") or "").strip()
        # 近重复去毒：同一段参考只算一次
        seen, uniq = set(), []
        for i in idxs:
            if rows[i]["ref_text"] not in seen:
                seen.add(rows[i]["ref_text"])
                uniq.append(i)
        m = len(uniq)
        pres: Counter[str] = Counter()
        for i in uniq:
            pres.update(ref_ng[i].keys())

        def build(g: str) -> dict:
            k = pres.get(g, 0)
            rec = k / m
            prec = k / df[g] if df.get(g) else 0.0
            # 出现次数吻合度：|A| 条里，参考中 g 的次数与源文中术语次数相等的比例
            fit = sum(1 for i in uniq if ref_ng[i].get(g, 0) == src_count(i, term)) / m
            return {"zh": g, "count": k, "recall": rec, "precision": prec,
                    "countfit": fit, "score": rec * prec * (0.5 + 0.5 * fit)}

        raw = {g for g, k in pres.items()
               if k / m >= MIN_RECALL and k / df[g] >= MIN_PRECISION}
        # 先削首尾语法字，再筛"像术语"的，最后去重
        pool = {trim(g) for g in raw}
        pool = {g for g in pool if term_like(g) and g in df}
        cand = [build(g) for g in pool]
        cand = [d for d in cand
                if d["recall"] >= MIN_RECALL and d["countfit"] >= MIN_COUNTFIT]
        # 片段抑制：若某候选是另一候选的子串且 recall 不更高，判为片段丢弃
        cand.sort(key=lambda d: (-d["recall"], -len(d["zh"]), -d["score"]))
        kept: list[dict] = []
        for d in cand:
            if any(d["zh"] in k["zh"] and d["recall"] <= k["recall"] + 1e-9 for k in kept):
                continue
            kept.append(d)
        kept.sort(key=lambda d: -d["score"])
        if target and not any(k["zh"] == target for k in kept):
            d = build(target)
            d["is_target"] = True
            kept.append(d)
        return kept[:8], m

    ledger = []
    for src, idxs in sorted(inst.items(), key=lambda kv: -len(kv[1])):
        t = tmeta[src]
        target = str(t.get("target_term") or "").strip()
        m = len(idxs)
        hits = sum(1 for i in idxs
                   if target_present(rows[i]["hypothesis_qwen36_40004"], t))
        rate = hits / m
        cand, m_uniq = candidates(idxs, t)
        real = [c for c in cand if not c.get("is_target")]
        uniq_refs = {rows[i]["ref_text"] for i in idxs}
        tgt_in_ref = sum(1 for rf in uniq_refs if target and target in rf)
        tgt_recall = tgt_in_ref / m_uniq
        # 与目标译法同族（互为子串）的候选不算"相悖"——那是同一种写法的长短形
        def same_family(g: str) -> bool:
            return bool(target) and (g in target or target in g)

        rival = next((c for c in real if not same_family(c["zh"])), None)

        # 分类，只看参考语料
        if m < MIN_INSTANCES:
            cls = "样本不足"
        elif tgt_recall >= MIN_RECALL and (rival is None
                                           or rival["recall"] <= tgt_recall + 0.15):
            cls = "一致"
        elif rival is not None and rival["recall"] > tgt_recall + 0.15:
            cls = "相悖"
        elif tgt_recall >= MIN_RECALL:
            cls = "一致"
        else:
            # 现译法在参考里查不到，但也没找到可信的替代写法 —— 不得断言参考写法
            cls = "无法验证"

        adj = ADJUDICATION.get(src)
        dom, dom_n, dom_rec = (rival["zh"] if rival else "",
                               rival["count"] if rival else 0,
                               rival["recall"] if rival else 0.0)
        auto_cls = cls
        if adj:
            cls = {"conflict": "相悖", "unverifiable": "无法验证",
                   "spacing": "空格差异", "agree": "一致"}[adj["verdict"]]
            if adj["ref_form"]:
                dom, dom_n = adj["ref_form"], adj["ref_count"]

        ledger.append({
            "term_id": t.get("term_id", ""), "source_term": src, "target_term": target,
            "target_aliases": t.get("target_aliases", []),
            "instances": m, "distinct_refs": m_uniq, "tcr_hits": hits, "tcr_rate": rate,
            "target_in_ref": tgt_in_ref, "target_ref_recall": tgt_recall,
            "ref_top": [{k: (round(v, 4) if isinstance(v, float) else v)
                         for k, v in c.items()} for c in cand[:5]],
            "ref_dominant": dom, "ref_dominant_count": dom_n,
            "ref_dominant_recall": dom_rec,
            "class": cls, "class_auto": auto_cls,
            "adjudicated": bool(adj),
            "adjudication_why": adj["why"] if adj else "",
            # 排序键：被主动推错的实例数 = 实例数 × 命中率（模型照我们说的做了，但参考不这么写）
            "pushed_wrong": round(m * rate, 1) if cls in ("相悖", "空格差异") else 0.0,
        })

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "t5_ledger.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in ledger) + "\n", encoding="utf-8")

    by = Counter(e["class"] for e in ledger)
    inst_by = Counter()
    for e in ledger:
        inst_by[e["class"]] += e["instances"]
    print("=" * 96)
    print("分类汇总")
    print("=" * 96)
    for k in ("一致", "相悖", "空格差异", "无法验证", "样本不足"):
        print(f"   {k:6s} 术语 {by[k]:3d} 条，实例 {inst_by[k]:4d} "
              f"({inst_by[k]/total_inst:5.1%})")

    conf = sorted([e for e in ledger if e["class"] == "相悖"],
                  key=lambda e: -e["pushed_wrong"])
    spacing = [e for e in ledger if e["class"] == "空格差异"]
    n_adj = sum(1 for e in ledger if e["adjudicated"])
    print(f"   （其中 {n_adj} 条经人工对照参考原文裁定，自动分类被改写的见 class_auto）")
    print()
    print("=" * 96)
    print("【相悖】按 实例数 × 命中率 = 被推错实例数 排序")
    print("=" * 96)
    print(f"{'term_id':>16s} {'源术语':28s} {'现译法':12s} {'参考实际写法(次)':22s} "
          f"{'实例':>4s} {'命中率':>7s} {'推错':>6s}")
    for e in conf:
        top = f"{e['ref_dominant']}({e['ref_dominant_count']})"
        print(f"{e['term_id']:>16s} {e['source_term'][:27]:28s} {e['target_term'][:11]:12s} "
              f"{top[:21]:22s} {e['instances']:4d} {e['tcr_rate']:7.1%} {e['pushed_wrong']:6.1f}")
    print(f"\n   相悖合计被推错实例：{sum(e['pushed_wrong'] for e in conf):.0f}")
    if spacing:
        print()
        print("=" * 96)
        print("【空格差异】译法与参考相同，只差拉丁字母两侧空格——改法与相悖类不同")
        print("=" * 96)
        for e in spacing:
            print(f"{e['term_id']:>16s} {e['source_term'][:27]:28s} "
                  f"现「{e['target_term']}」 参考「{e['ref_dominant']}」 "
                  f"实例 {e['instances']} 命中率 {e['tcr_rate']:.1%}")

    unv = sorted([e for e in ledger if e["class"] == "无法验证"], key=lambda e: -e["instances"])
    print()
    print("=" * 96)
    print("【无法验证】参考里查不到对应写法——不得默认正确")
    print("=" * 96)
    print(f"{'term_id':>16s} {'源术语':28s} {'现译法':12s} {'实例':>4s} {'命中率':>7s} "
          f"{'target在参考中的召回':>18s}")
    for e in unv[:40]:
        print(f"{e['term_id']:>16s} {e['source_term'][:27]:28s} {e['target_term'][:11]:12s} "
              f"{e['instances']:4d} {e['tcr_rate']:7.1%} {e['target_ref_recall']:18.1%}")
    if len(unv) > 40:
        print(f"   … 另有 {len(unv)-40} 条，见 t5_ledger.jsonl")

    summary = {
        "corpus": RESULTS, "n_rows": len(rows), "n_hard_terms": len(inst),
        "total_instances": total_inst,
        "thresholds": {"min_recall": MIN_RECALL, "min_precision": MIN_PRECISION,
                       "min_instances": MIN_INSTANCES, "ngram": [NMIN, NMAX]},
        "by_class": {k: {"terms": by[k], "instances": inst_by[k]} for k in by},
        "conflict_total_pushed_wrong": sum(e["pushed_wrong"] for e in conf),
        "conflict": conf, "unverifiable": unv,
    }
    (OUT / "t5_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {OUT/'t5_ledger.jsonl'}\n-> {OUT/'t5_summary.json'}")


if __name__ == "__main__":
    main()
