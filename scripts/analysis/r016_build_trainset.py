#!/usr/bin/env python3
"""R016 → **微调训练集**（不进评测集，不并入 all_eval）。

定位（2026-07-28 决定）
----------------------
R016 不进评测集：TCR 现在 96.43%、离 95% 门禁只有 1.43pp 余量，塞进 640 条
术语覆盖未知的新语料很可能击穿门禁。作为训练集则：
    训 = R016 640 对    评 = R100+R17 689 条
评测集原封不动、天然 held-out，不用重新封版、不用重算任何对外数字。

配对方式：**合订本内部奇偶页配对**
----------------------------------
`R016_08_series_zh.pdf` 是中英对照合订本，奇数页英文、偶数页中文。
源 = 奇数页英文段，参考 = 下一偶数页的同条款号中文段。
**不与 `R016_08_series_en.pdf` 配对** —— 那是不同版次（逐页相似度仅 0.52–0.85），
跨版次配对不触发任何比值护栏，只会均匀压低分数，几轮都查不出来。

过滤口径：**训练集标准，不是验收标准**
--------------------------------------
只剔"明确会教坏模型"的几类，不追求逐行可辩护：
    源文截断    R2 / R2a / R2b —— 教模型多译
    粒度不对等  G2（比值法）    —— 教模型少译
    水印        R3             —— 教模型把广告翻进正文
    孤儿段      无条款号        —— 训练集第一检查项
B（参考过覆盖）/ R4（表格行）/ R5（下标塌陷）**不剔**：它们让评测分数偏移，
但不构成方向性的错误示范。这是与验收口径的**有意差异**。

G1 需要参考侧分段上下文，这里用同源的等价判据：中文段之后紧跟无条款号孤儿段。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.evaluation.acceptance_subset import (  # noqa: E402
    _SEC, _TERM, _DANG, _COLON_END, _watermark_hit, _BRK,
    HEALTHY_RATIO, G2_MIN_SOURCE, G2_COVERAGE, RATIO_CUT,
)
from scripts.evaluation.prepare_da_pairs import parse_pdf_segments, MAX_SEGMENT_CHARS  # noqa: E402

CJK = re.compile(r"[一-鿿]")
LAT = re.compile(r"[A-Za-z]")


def is_zh(t: str) -> bool:
    return len(CJK.findall(t)) > len(LAT.findall(t))


def train_reject(src: str, ref: str, orphan_after: bool) -> list[tuple[str, str]]:
    """训练集过滤。只留会教坏模型的类别。"""
    out: list[tuple[str, str]] = []
    ns, nr = len(src), len(ref)

    body = _SEC.sub("", src).strip()
    if not _TERM.search(src) and _DANG.search(src):
        out.append(("R2", f"源文无句末标点、以功能词 “{src.strip().split()[-1]}” 结尾 → 教模型多译"))
    elif not _TERM.search(src) and _TERM.search(ref) and not _COLON_END.search(src):
        out.append(("R2a", "源文无句末标点也不以冒号结束，而参考是完整条款 → 源文被截断，教模型多译"))
    if nr / max(ns, 1) > RATIO_CUT:
        out.append(("R2b", f"参考/源文字符比 {nr/max(ns,1):.2f} > {RATIO_CUT} → 源文只覆盖条款一部分"))

    for side, text in (("源文", src), ("参考", ref)):
        why = _watermark_hit(text)
        if why:
            out.append(("R3", f"{side}含{why} → 教模型把广告翻进正文"))
            break
    for b in _BRK:
        if b in src or b in ref:
            out.append(("R3", f"含 PDF 抽取失败标记 “{b}”"))
            break

    expected = HEALTHY_RATIO * ns
    if ns > G2_MIN_SOURCE and nr < expected * G2_COVERAGE:
        out.append(("G2", f"源文 {ns} 字，参考仅 {nr} 字（期望约 {expected:.0f}）→ 粒度不对等，教模型少译"))
    if orphan_after:
        out.append(("G1", "参考段之后紧跟无条款号孤儿段 → 参考只拿到第一段，教模型少译"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default="data/raw/en-zh/R016_08_series_zh.pdf")
    ap.add_argument("--out-dir", default="data/train/r016_20260728")
    args = ap.parse_args()

    segs = parse_pdf_segments(Path(args.pdf), "R016_08_series", "en-zh", "zh",
                              min_chars=2, max_chars=MAX_SEGMENT_CHARS)[0]
    for s in segs:
        s["page"] = int(s["page"])
        s["zh"] = is_zh(s["text"])
        s["sec"] = None if s["section_no"] in ("None", "", None) else s["section_no"]

    en_by_page: dict[int, list[dict]] = {}
    for s in segs:
        if not s["zh"]:
            en_by_page.setdefault(s["page"], []).append(s)
    # 同页内按 order 排，用于判"之后是否紧跟孤儿段"
    by_page_all: dict[int, list[dict]] = {}
    for s in segs:
        by_page_all.setdefault(s["page"], []).append(s)
    for v in by_page_all.values():
        v.sort(key=lambda x: int(x["order"]))

    pairs, stats = [], Counter()
    for s in segs:
        if not s["zh"] or not s["sec"]:
            continue
        cand = en_by_page.get(s["page"] - 1, [])
        hit = [e for e in cand if e["sec"] == s["sec"]]
        if not hit:
            stats["未配上"] += 1
            continue
        e = hit[0]
        sib = by_page_all[s["page"]]
        i = sib.index(s)
        orphan_after = (i + 1 < len(sib) and sib[i + 1]["zh"] and not sib[i + 1]["sec"])
        pairs.append((e, s, orphan_after))

    kept, dropped = [], []
    for e, z, orph in pairs:
        rej = train_reject(e["text"], z["text"], orph)
        rec = {
            "sample_id": f"R016_08_series_en-zh_{len(kept)+len(dropped):06d}",
            "document_id": "R016_08_series", "language_pair": "en-zh",
            "source_lang": "en", "target_lang": "zh",
            "section_no": z["sec"], "page_en": e["page"], "page_zh": z["page"],
            "source_text": e["text"], "target_text": z["text"],
            "source_char_count": len(e["text"]), "target_char_count": len(z["text"]),
            "pairing": "bilingual_facing_page(odd=en,even=zh)",
        }
        if rej:
            rec["reject_rules"] = sorted(r for r, _ in rej)
            rec["reject_reasons"] = [w for _, w in rej]
            dropped.append(rec)
            for r, _ in rej:
                stats[f"剔除:{r}"] += 1
        else:
            kept.append(rec)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "train_pairs.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in kept) + "\n", encoding="utf-8")
    (out / "rejected.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in dropped) + "\n", encoding="utf-8")

    ratios = sorted(r["target_char_count"] / max(r["source_char_count"], 1) for r in kept)
    summary = {
        "pdf": args.pdf, "pairing": "合订本奇偶页内部配对，不跨 PDF",
        "purpose": "微调训练集，不进评测集、不并入 all_eval",
        "pairs_found": len(pairs), "kept": len(kept), "dropped": len(dropped),
        "drop_rate": round(len(dropped) / max(len(pairs), 1), 4),
        "rule_hits": {k: v for k, v in stats.items()},
        "orphan_rate_in_kept": 0.0,
        "ratio_p10": ratios[int(.1 * len(ratios))] if ratios else None,
        "ratio_p50": ratios[len(ratios) // 2] if ratios else None,
        "ratio_p90": ratios[int(.9 * len(ratios))] if ratios else None,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n-> {out/'train_pairs.jsonl'}  ({len(kept)} 对)")
    print(f"-> {out/'rejected.jsonl'}    ({len(dropped)} 对，含逐条理由)")


if __name__ == "__main__":
    main()
