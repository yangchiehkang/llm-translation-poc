#!/usr/bin/env python3
"""B/C — 对扫描件 / 字体子集映射损坏的 PDF 做 OCR，产出带文本层的可检索 PDF。

用途有两处，成因不同但修法相同（都绕开 PDF 内嵌文本层）：

* **th DLT_BE2563**：纯扫描件，4 页、文本层 0 字符，从头到尾没被用过。
* **ar SASO**：有文本层，但字体子集的 ToUnicode 映射表有缺失，抽出来的字符里
  混着替换噪声（`تɢون`、`المعاɲي`）。映射表是 PDF 制作时就丢的信息，抽取端补不回来；
  OCR 走像素，绕开整个问题。

做法：PyMuPDF 按 `--dpi` 渲染每页 → tesseract 逐页出**单页可检索 PDF**
（`pdf` 输出，保留原图 + 不可见文本层）→ PyMuPDF 合并成一份。产物与原始 PDF
同构，下游 `parse_pdf_segments()` 不需要任何改动即可读。

用法（在装有 tesseract 且带对应语言包的机器上跑）：
    python a2_ocr_pdf.py --input X.pdf --output X_ocr.pdf --lang tha --dpi 400
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def ocr_pdf(src: Path, dst: Path, lang: str, dpi: int, psm: int) -> dict:
    import fitz

    if not shutil.which("tesseract"):
        raise RuntimeError("tesseract not found on PATH")
    doc = fitz.open(src)
    out = fitz.open()
    per_page = []
    page_texts: list[dict] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for i, page in enumerate(doc):
            png = tmp / f"p{i:04d}.png"
            page.get_pixmap(dpi=dpi).save(png)
            stem = tmp / f"p{i:04d}"
            cmd = ["tesseract", str(png), str(stem), "-l", lang,
                   "--psm", str(psm), "--dpi", str(dpi), "pdf"]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"tesseract failed on page {i+1}: {r.stderr[:400]}")
            piece = fitz.open(str(stem) + ".pdf")
            out.insert_pdf(piece)
            piece.close()
            # 纯文本输出与 pdf 输出同一次识别结果，但**文本顺序不同**：
            # tesseract 的 pdf 输出把字形按**视觉位置**摆放，PyMuPDF/pdfplumber
            # 读回来时 RTL（阿拉伯语）整行是倒的（词序和词内字序同时反过来，
            # 实测整行 `[::-1]` 正好还原）；而 .txt 输出本身就是**逻辑顺序**。
            # 与其在下游猜"这份 PDF 是不是 OCR 产物、要不要整行倒置"，不如在
            # 这里就把逻辑顺序的文本落成 sidecar，由 extract_pages() 直接采用。
            r2 = subprocess.run(["tesseract", str(png), str(stem), "-l", lang,
                                 "--psm", str(psm), "--dpi", str(dpi)],
                                capture_output=True, text=True)
            if r2.returncode != 0:
                raise RuntimeError(f"tesseract(txt) failed on page {i+1}: {r2.stderr[:400]}")
            txt = Path(str(stem) + ".txt").read_text(encoding="utf-8").strip()
            page_texts.append({"page": i + 1, "text": txt})
            per_page.append({"page": i + 1, "chars": len(txt)})
            print(f"  page {i+1}/{len(doc)}: {len(txt)} chars", flush=True)
        out.save(dst)
    Path(str(dst) + ".pages.json").write_text(
        json.dumps(page_texts, ensure_ascii=False), encoding="utf-8")
    total = sum(p["chars"] for p in per_page)
    return {"input": str(src), "output": str(dst), "sidecar": str(dst) + ".pages.json",
            "lang": lang, "dpi": dpi,
            "psm": psm, "pages": len(per_page), "total_chars": total,
            "per_page": per_page}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--lang", required=True, help="tesseract 语言代码，如 tha / ara / chi_sim")
    ap.add_argument("--dpi", type=int, default=400)
    ap.add_argument("--psm", type=int, default=3)
    ap.add_argument("--report", default="")
    a = ap.parse_args()

    rep = ocr_pdf(Path(a.input), Path(a.output), a.lang, a.dpi, a.psm)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if a.report:
        Path(a.report).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
