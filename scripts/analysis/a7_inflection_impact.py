#!/usr/bin/env python3
"""D — 屈折语形态匹配缺口的**影响面测量**（只测量，不改生产代码）。

发现：`scripts/common/termbase.match_terms()` 用「精确表层字符串 + 词边界」匹配。
对英语基本够用，对**屈折语**系统性失效——俄语名词有六个格、单复数，法规正文里
几乎不出现术语库收录的主格单数形。实测这些句子 match_terms 返回**空**：

    "При проведении других видов испытаний…"        术语库有 испытание   → 0 命中
    "…системами вентиляции, отопления и кондиционирования"
                                                    三条术语全在库里     → 0 命中
    "Требования к системе кондиционирования…"       库有 система кондиционирования → 0 命中

即 ru 的"含术语句 70/130 = 53.8%"**不是术语库太小造成的**（ru 库已含
испытание/вентиляция/отопление/кондиционирование/температура 等全部相关条目），
是匹配层吃不掉词形变化。这是本项目"拉丁书写惯例被当成全语种通用规律"的第十次同型 bug。

⚠️ `match_terms` 是**生产代码路径**（api/backends 也调它），改它会同时改动 TCR
门禁与线上术语注入行为。因此本脚本只做**影响面测量**：用一个词尾容忍的匹配变体
重算"含术语句"，给出如果修会多多少，不落地任何改动。

用法：
    python scripts/analysis/a7_inflection_impact.py --pairs <lang>_sent_pairs.jsonl --lang ru
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.common.termbase import load_termbase, match_terms  # noqa: E402

# 各语言的屈折后缀（只砍词尾，不做真正的形态分析）。
# ru：名词六格 + 复数；de：第二格/复数/形容词弱变化。
SUFFIXES = {
    "ru": ["ями", "ами", "иями", "ов", "ев", "ей", "ой", "ые", "ый", "ий", "ая", "ое",
           "ие", "ем", "ом", "ым", "им", "ах", "ях", "ую", "юю", "а", "я", "ы", "и",
           "о", "е", "у", "ю", "ь"],
    "de": ["ungen", "en", "es", "er", "em", "s", "e", "n"],
    "es": ["es", "s", "as", "os", "a", "o"],
    "fr": ["aux", "es", "s", "x"],
}
MIN_STEM = 5


def stem_variants(term: str, lang: str) -> str | None:
    """把术语的每个词做词尾裁剪，拼成一个允许任意词尾的正则。"""
    sufs = SUFFIXES.get(lang)
    if not sufs:
        return None
    words = re.findall(r"\w+", term, re.UNICODE)
    if not words:
        return None
    parts = []
    for w in words:
        wl = w.lower()
        base = wl
        for s in sorted(sufs, key=len, reverse=True):
            if len(wl) - len(s) >= MIN_STEM and wl.endswith(s):
                base = wl[: -len(s)]
                break
        if len(base) < 3:
            base = wl
        parts.append(re.escape(base) + r"\w*")
    return r"(?<!\w)" + r"[\s\-,]+".join(parts) + r"(?!\w)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--lang", required=True)
    ap.add_argument("--termbase", default=str(ROOT / "termbase/auto_regulation_terms_v1.csv"))
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    rows = [json.loads(l) for l in Path(a.pairs).read_text(encoding="utf-8").splitlines() if l.strip()]
    terms = load_termbase(a.termbase, source_lang=a.lang, target_lang="zh")
    pats = []
    for t in terms:
        p = stem_variants(str(t.get("source_term") or ""), a.lang)
        if p:
            try:
                pats.append((re.compile(p, re.IGNORECASE), t))
            except re.error:
                continue

    exact_hit = tol_hit = 0
    gained = []
    for r in rows:
        src = r["source_text"]
        e = bool(match_terms(src, terms))
        exact_hit += e
        if e:
            tol_hit += 1
            continue
        hits = [t for rx, t in pats if rx.search(src)]
        if hits:
            tol_hit += 1
            gained.append({"sample_id": r["sample_id"],
                           "terms": [t.get("source_term") for t in hits[:5]],
                           "src": src[:130], "ref": r["ref_text"][:90]})

    n = len(rows)
    print(f"{a.lang}: 句级单元 {n}")
    print(f"  现行精确匹配含术语句 : {exact_hit:4d} ({exact_hit/max(1,n):.1%})")
    print(f"  词尾容忍匹配含术语句 : {tol_hit:4d} ({tol_hit/max(1,n):.1%})   净增 {tol_hit-exact_hit}")
    print(f"\n新命中的句子样例（术语库本来就收录了这些词，只是词形不同）：")
    for g in gained[:8]:
        print(f"  + {g['terms']}")
        print(f"      {g['src']}")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(
            {"lang": a.lang, "units": n, "exact": exact_hit, "tolerant": tol_hit,
             "gain": tol_hit - exact_hit, "examples": gained}, ensure_ascii=False, indent=2),
            encoding="utf-8")


if __name__ == "__main__":
    main()
