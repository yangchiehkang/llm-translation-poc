#!/usr/bin/env python3
"""B — 泰文 OCR 质量标定：在**有真实文本层的**同族文档上量 OCR 字符错误率。

要回答的问题是"BE2563 的 OCR 产物能不能当语料用"。BE2563 本身是扫描件、没有
ground truth，直接看输出只能"看着还行"。但同一个发布机关、同一套排版的
DLT_BE2560 有完好的文本层（96k 字符）——把它渲染成图再 OCR，拿 OCR 结果与它
自己的文本层对比，得到的 CER 就是这套 OCR 配置在**这类文档**上的真实水平，
可以外推到 BE2563。

同时对比几组 tesseract 配置（psm / preserve_interword_spaces），选 CER 最低的。

用法（需 tesseract + tha 语言包）：
    python a3_ocr_calibrate.py --pdf DLT_BE2560_seat_belt_anchorage_th.pdf --pages 5,10,20
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

THAI_RE = re.compile(r"[฀-๿]")

CONFIGS = [
    {"name": "psm3", "psm": 3, "extra": []},
    {"name": "psm6", "psm": 6, "extra": []},
    {"name": "psm6_iws", "psm": 6, "extra": ["-c", "preserve_interword_spaces=1"]},
    {"name": "psm4", "psm": 4, "extra": []},
]


def normalize(text: str, drop_all_spaces: bool) -> str:
    """归一化到可比形式。

    泰文本身**词间不加空格**，行内空格几乎全是排版/OCR 产物；比对时统一去掉
    所有空白，避免把"空格位置不同"算成字符错误——我们要量的是**字形识别**准确率。
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    if drop_all_spaces:
        text = re.sub(r"\s+", "", text)
    return text


def cer(ref: str, hyp: str) -> float:
    """字符级编辑距离 / 参考长度（Levenshtein，O(len(ref)*len(hyp)) 空间优化版）。"""
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(ref)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--pages", default="5,10,20", help="1-based 页号，逗号分隔")
    ap.add_argument("--lang", default="tha")
    ap.add_argument("--dpi", type=int, default=400)
    ap.add_argument("--report", default="")
    a = ap.parse_args()

    import fitz

    doc = fitz.open(a.pdf)
    pages = [int(x) for x in a.pages.split(",") if x.strip()]
    results = {c["name"]: [] for c in CONFIGS}
    samples = []

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for pno in pages:
            page = doc[pno - 1]
            truth_raw = page.get_text().strip()
            if len(THAI_RE.findall(truth_raw)) < 100:
                print(f"page {pno}: 文本层泰文字符太少（{len(THAI_RE.findall(truth_raw))}），跳过", flush=True)
                continue
            png = tmp / f"p{pno}.png"
            page.get_pixmap(dpi=a.dpi).save(png)
            truth = normalize(truth_raw, drop_all_spaces=True)
            for c in CONFIGS:
                stem = tmp / f"p{pno}_{c['name']}"
                cmd = ["tesseract", str(png), str(stem), "-l", a.lang,
                       "--psm", str(c["psm"]), "--dpi", str(a.dpi), *c["extra"]]
                r = subprocess.run(cmd, capture_output=True, text=True)
                if r.returncode != 0:
                    print(f"  {c['name']} FAILED: {r.stderr[:200]}", flush=True)
                    continue
                hyp = normalize(Path(str(stem) + ".txt").read_text(encoding="utf-8"), drop_all_spaces=True)
                e = cer(truth, hyp)
                results[c["name"]].append(e)
                print(f"page {pno} {c['name']:10s} CER={e:.4f} (truth {len(truth)} chars, ocr {len(hyp)})", flush=True)
                if c["name"] == "psm6" and len(samples) < 3:
                    samples.append({"page": pno, "truth": truth[:200], "ocr": hyp[:200]})

    summary = {"pdf": a.pdf, "dpi": a.dpi, "lang": a.lang, "pages": pages,
               "cer_by_config": {k: (sum(v) / len(v) if v else None) for k, v in results.items()},
               "samples": samples}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if a.report:
        Path(a.report).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
