#!/usr/bin/env python3
"""D — RU 术语库覆盖率审计（中文端锚定法）。

**第一版方法作废**：先按俄语词频找"高频未收录词"，产出的全是 места / наличии /
течение / которой 这类普通词的变格形式，中文候选也只是段落里最常见的词
（车辆/系统/温度），没有判别力。词频 + 共现在这个语料规模（138 条）上根本不成立。

**本版方法**：七个语向的术语库 `target_term` 全是中文，覆盖的是**同一个领域**
（汽车法规）。因此可以在中文端做差集：某个概念（如"制动距离"）在 en/de/fr 的
术语库里有、在 ru 的没有，就是 ru 侧的**真实覆盖缺口**——依据是其它语向已经
人工确认过这是专业术语，不是我按词频猜的。

再对每个缺口概念，在 ru 对齐语料里定位：
  ① 参考中文侧包含该 target_term 的样本
  ② 这些样本的俄语源文里，相对全语料**显著富集**的词（PMI 式打分），即候选俄语术语
  ③ 富集度与出现次数一并报出，供人工核对

纪律：**只提候选、不自动入库**。没有语料证据的概念标为 no_evidence，不硬凑。

用法：
    python scripts/analysis/a5_ru_term_gap.py --aligned <ru_zh_aligned_da_samples.jsonl> --out <dir>
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.common.termbase import load_termbase, match_terms  # noqa: E402

WORD = re.compile(r"[А-Яа-яЁё][А-Яа-яЁё-]{2,}")


def stem(w: str) -> str:
    """极简俄语词干：砍掉常见屈折后缀。够用于把同一词的变格形式并到一起。"""
    w = w.lower()
    for suf in ("ированием", "ированию", "ирования", "ование", "ования", "ованию",
                "ами", "ями", "ов", "ев", "ах", "ях", "ой", "ей", "ую", "юю",
                "ые", "ий", "ый", "ая", "ое", "ие", "ем", "ом", "ым", "им",
                "а", "я", "ы", "и", "о", "е", "у", "ю"):
        if len(w) - len(suf) >= 5 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aligned", required=True)
    ap.add_argument("--termbase", default=str(ROOT / "termbase/auto_regulation_terms_v1.csv"))
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    tb = list(csv.DictReader(open(a.termbase, encoding="utf-8")))
    by_lang: dict[str, set[str]] = defaultdict(set)
    zh_meta: dict[str, list[str]] = defaultdict(list)
    for r in tb:
        if (r.get("status") or "") != "active":
            continue
        zh = (r.get("target_term") or "").strip()
        if not zh:
            continue
        by_lang[r["source_lang"]].add(zh)
        zh_meta[zh].append(f"{r['source_lang']}:{r['source_term']}")

    mine = by_lang.get(a.lang, set())
    others = set().union(*(v for k, v in by_lang.items() if k != a.lang))
    missing = sorted(others - mine)

    rows = [json.loads(l) for l in Path(a.aligned).read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("alignment_method") == "exact_section_scoped"]

    # 全语料词干分布（背景分布）
    bg: Counter[str] = Counter()
    doc_stems: list[set[str]] = []
    for r in rows:
        s = {stem(w) for w in WORD.findall(r["source_text"])}
        doc_stems.append(s)
        bg.update(s)
    n_docs = len(rows)

    results = []
    for zh in missing:
        hits = [i for i, r in enumerate(rows) if zh in r["ref_text"]]
        if not hits:
            results.append({"zh": zh, "in_langs": zh_meta[zh], "corpus_hits": 0,
                            "status": "no_evidence", "candidates": []})
            continue
        local: Counter[str] = Counter()
        for i in hits:
            local.update(doc_stems[i])
        cands = []
        for st, c in local.most_common(60):
            if c < 2 or len(st) < 5:
                continue
            # PMI 式富集：该词干在命中集中的比例 / 在全语料中的比例
            p_local = c / len(hits)
            p_bg = bg[st] / n_docs
            if p_bg <= 0:
                continue
            lift = p_local / p_bg
            if lift < 1.5:
                continue
            forms = Counter()
            for i in hits:
                for w in WORD.findall(rows[i]["source_text"]):
                    if stem(w) == st:
                        forms[w.lower()] += 1
            cands.append({"stem": st, "surface": forms.most_common(1)[0][0] if forms else st,
                          "in_hits": c, "in_corpus": bg[st], "lift": round(lift, 2)})
        cands.sort(key=lambda x: (-x["lift"], -x["in_hits"]))
        results.append({
            "zh": zh, "in_langs": zh_meta[zh], "corpus_hits": len(hits),
            "status": "has_candidate" if cands else "hits_but_no_distinctive_term",
            "sample_ids": [rows[i]["sample_id"] for i in hits[:5]],
            "candidates": cands[:4],
        })

    dest = Path(a.out)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{a.lang}_term_gap_candidates.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    terms = load_termbase(a.termbase, source_lang=a.lang, target_lang="zh")
    with_terms = sum(1 for r in rows if match_terms(r["source_text"], terms))
    strong = [r for r in results if r["status"] == "has_candidate" and r["corpus_hits"] >= 2
              and r["candidates"] and r["candidates"][0]["lift"] >= 2.0]

    print(f"{a.lang} 术语库 {len(mine)} 个中文概念；其它六语向合计 {len(others)} 个")
    print(f"{a.lang} 缺口概念（其它语向有、ru 没有）：{len(missing)} 个")
    print(f"  其中在 ru 语料里有出现证据的：{sum(1 for r in results if r['corpus_hits'] > 0)} 个")
    print(f"  且能定位到显著富集的俄语候选词（lift≥2.0、命中≥2）：{len(strong)} 个")
    print(f"\n现有术语库在 {len(rows)} 条 exact 样本上命中 {with_terms} 条 ({with_terms/max(1,len(rows)):.1%})\n")
    print(f"{'中文概念':16s}{'语料命中':>6s}{'其它语向来源':38s} 俄语候选(lift)")
    for r in strong[:30]:
        c = r["candidates"][0]
        src = ", ".join(r["in_langs"][:2])
        print(f"{r['zh']:16s}{r['corpus_hits']:6d}  {src[:36]:38s} {c['surface']}({c['lift']})")
    print(f"\nwrote {dest}/{a.lang}_term_gap_candidates.json")


if __name__ == "__main__":
    main()
