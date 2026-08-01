#!/usr/bin/env python3
"""A — DE/ES 参考侧噪声逐类审计。

对每一条被丢弃的行归到**唯一一个**类别（按 is_noise_line/repeated_page_lines 的实际
判定顺序），统计命中行数与字符数。目的是回答一个问题：DE/ES 的自比对上界低，
是"参考侧噪声没清干净"还是"目标定得过高"。

只统计，不改抽取器。用法：
    python scripts/analysis/a1_ref_noise_audit.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.evaluation.prepare_da_pairs import (  # noqa: E402
    clean_text,
    is_repeated_page_line,
    extract_pages,
    good_char_ratio,
    is_noise_line,
    repeated_page_lines,
)

DOCS = {
    "de": [
        "StVZO_road_traffic_licensing_regulations",
        "Circular_Economy_Waste_Management_Act",
    ],
    "es": [
        "Decreto_119_2012_antitheft",
        "Resolucion_816_Exenta_2023",
    ],
}


def classify(line: str, repeated: dict) -> str:
    """把一行归到唯一一个丢弃类别；不丢弃则返回 'kept'。

    顺序与 is_noise_line() 内部顺序一致，再补 repeated_page_lines 这一层。
    """
    c = clean_text(line)
    if not c:
        return "empty"
    if re.fullmatch(r"[-–—]?\s*\d{1,4}\s*[-–—]?", c):
        return "bare_page_number"
    if re.fullmatch(r"(?:page|página|seite|страница|หน้า)\s+\d{1,4}(?:\s*/\s*\d{1,4})?", c, re.IGNORECASE):
        return "page_x_of_y_latin"
    if re.fullmatch(r"第\s*\d{1,4}\s*页\s*共\s*\d{1,4}\s*页", c):
        return "page_x_of_y_zh"
    if re.search(r"[.·…]{4,}\s*\d{1,4}$", c):
        return "toc_dotted_leader"
    if re.search(r"[.·…]{10,}", c):
        return "dotted_run"
    if len(c) > 20 and good_char_ratio(c) < 0.25:
        return "low_good_char_ratio"
    if is_repeated_page_line(c, repeated):
        return "repeated_header_footer"
    return "kept"


# 这些是 *当前规则没抓到* 的候选噪声类；只探测、只统计，不落地为过滤规则。
PROBES: dict[str, re.Pattern[str]] = {
    "probe_watermark_gesetze": re.compile(r"gesetze-im-internet\.de|联邦司法部和联邦司法局的一项服务", re.IGNORECASE),
    "probe_juris_footer": re.compile(r"juris\s*GmbH|Ein Service des Bundesministeriums", re.IGNORECASE),
    "probe_zh_page_of": re.compile(r"^\s*第\s*\d+\s*页\s*，?\s*共\s*\d+\s*页\s*$"),
    "probe_stand_datum": re.compile(r"^\s*(Stand|Zuletzt geändert)\b"),
    "probe_toc_line": re.compile(r"^\s*(§+\s*\d+[a-z]?|Anlage\s+[IVXLC0-9]+)\s+.{2,60}\s+\d{1,4}\s*$"),
    "probe_es_footer": re.compile(r"Biblioteca del Congreso Nacional|www\.bcn\.cl|www\.leychile\.cl", re.IGNORECASE),
    "probe_es_page": re.compile(r"^\s*P[áa]gina\s+\d+\s+de\s+\d+\s*$", re.IGNORECASE),
    "probe_url_only": re.compile(r"^\s*(https?://|www\.)\S+\s*$", re.IGNORECASE),
}


def audit(pdf: Path) -> dict:
    pages = extract_pages(pdf)
    repeated = repeated_page_lines(pages)
    cls_lines: Counter[str] = Counter()
    cls_chars: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)
    probe_lines: Counter[str] = Counter()
    probe_chars: Counter[str] = Counter()
    probe_samples: dict[str, list[str]] = defaultdict(list)
    total_lines = total_chars = 0
    # 跨页断行：一页最后一个 kept 行不以句末标点/编号收尾，且下一页第一个 kept 行
    # 不以条款号/编号开头 —— 判定为一个被页边界切断的句子。
    hanging = 0
    hanging_samples: list[str] = []
    prev_tail: str | None = None

    for page in pages:
        page_kept: list[str] = []
        for raw in (page.get("text") or "").splitlines():
            c = clean_text(raw)
            if not c:
                continue
            total_lines += 1
            total_chars += len(c)
            k = classify(raw, repeated)
            cls_lines[k] += 1
            cls_chars[k] += len(c)
            if k != "kept" and len(samples[k]) < 5:
                samples[k].append(c[:120])
            if k == "kept":
                page_kept.append(c)
                for name, rx in PROBES.items():
                    if rx.search(c):
                        probe_lines[name] += 1
                        probe_chars[name] += len(c)
                        if len(probe_samples[name]) < 5:
                            probe_samples[name].append(c[:120])
        if page_kept:
            head = page_kept[0]
            if prev_tail is not None:
                tail_open = not re.search(r"[。．.！!？?；;：:）)】\]]$", prev_tail)
                head_cont = not re.match(
                    r"^\s*(§|第\s*\d|Artikel|Article|Anlage|Anhang|[（(]?\d{1,3}[.)）]|[A-Za-z]\))", head
                )
                if tail_open and head_cont:
                    hanging += 1
                    if len(hanging_samples) < 5:
                        hanging_samples.append(f"…{prev_tail[-60:]} ⏎ {head[:60]}…")
            prev_tail = page_kept[-1]

    return {
        "pdf": pdf.name,
        "pages": len(pages),
        "total_nonempty_lines": total_lines,
        "total_chars": total_chars,
        "dropped_by_class": {k: {"lines": cls_lines[k], "chars": cls_chars[k], "sample": samples[k]}
                             for k in sorted(cls_lines) if k != "kept"},
        "kept_lines": cls_lines["kept"],
        "kept_chars": cls_chars["kept"],
        "surviving_noise_probes": {k: {"lines": probe_lines[k], "chars": probe_chars[k],
                                       "sample": probe_samples[k]}
                                   for k in sorted(probe_lines)},
        "cross_page_hanging_breaks": hanging,
        "cross_page_hanging_samples": hanging_samples,
    }


def main() -> None:
    out = {}
    for lang, docs in DOCS.items():
        raw = ROOT / "data" / "raw" / f"{lang}-zh"
        for doc in docs:
            for side, suffix in (("ref_zh", "zh"), ("src", lang)):
                pdf = raw / f"{doc}_{suffix}.pdf"
                if not pdf.exists():
                    continue
                key = f"{lang}/{doc}/{side}"
                out[key] = audit(pdf)
                a = out[key]
                drop_lines = sum(v["lines"] for v in a["dropped_by_class"].values())
                probe_l = sum(v["lines"] for v in a["surviving_noise_probes"].values())
                print(f"{key}\n  pages={a['pages']} lines={a['total_nonempty_lines']} "
                      f"chars={a['total_chars']} | dropped {drop_lines} lines "
                      f"({sum(v['chars'] for v in a['dropped_by_class'].values())} chars) | "
                      f"kept {a['kept_lines']} lines / {a['kept_chars']} chars", flush=True)
                for k, v in a["dropped_by_class"].items():
                    print(f"    drop[{k}] {v['lines']} lines {v['chars']} chars", flush=True)
                for k, v in a["surviving_noise_probes"].items():
                    print(f"    SURVIVING[{k}] {v['lines']} lines {v['chars']} chars "
                          f"e.g. {v['sample'][:1]}", flush=True)
                print(f"    cross_page_hanging_breaks={a['cross_page_hanging_breaks']}", flush=True)
                if probe_l == 0:
                    print("    (no surviving probe hits)", flush=True)

    dest = ROOT / "outputs" / "analysis" / "a1_ref_noise_20260731"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "ref_noise_audit.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {dest / 'ref_noise_audit.json'}")


if __name__ == "__main__":
    main()
