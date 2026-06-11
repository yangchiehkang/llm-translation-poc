# -*- coding: utf-8 -*-
"""
Semantic monotonic alignment: src sentence JSONL -> ref_zh PDF segments.

Features:
- PDF body extraction with header/footer cropping + repeated template removal
- Chinese ref segmentation + merging title/paren/article fragments
- Strong garbage filtering for TOC/cover approval blocks/numbered lists/table fragments
- SentenceTransformer embeddings with disk cache
- Monotonic DP alignment allowing 1-1, 1-2, 2-1, skips
- Batch mode + skip existing outputs

Output: *.da.jsonl with fields: ref_text/ref_page_no/align_span/align_score/ref_doc
"""

import argparse
import json
import re
import hashlib
import unicodedata
from pathlib import Path
from collections import Counter

import numpy as np
import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer


# ----------------------------
# IO utils
# ----------------------------
def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def read_jsonl(path: Path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows):
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def sha1_text_list(texts: list[str]) -> str:
    h = hashlib.sha1()
    for t in texts:
        h.update((t or "").encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


# ----------------------------
# Normalization
# ----------------------------
def nfkc(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s)


def norm_ws(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\u00ad", "").replace("\ufeff", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def normalize_text(s: str) -> str:
    return norm_ws(nfkc(s or ""))


def collapse_pdf_linebreaks(s: str) -> str:
    """
    Make extracted PDF text look like normal prose:
    - turn single newlines into space
    - keep paragraph breaks compressed
    """
    t = normalize_text(s)
    if not t:
        return ""
    t = re.sub(r"(?<!\n)\n(?!\n)", " ", t)   # single \n -> space
    t = re.sub(r"\n{2,}", "\n", t)          # multi -> one para break
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


# ----------------------------
# PDF read (body-only by coordinates)
# ----------------------------
def read_pages_body(pdf_path: Path, header_frac=0.12, footer_frac=0.12):
    doc = fitz.open(str(pdf_path))
    pages = []
    for i in range(len(doc)):
        page = doc[i]
        H = float(page.rect.height)
        y0 = H * header_frac
        y1 = H * (1 - footer_frac)

        blocks = page.get_text("blocks") or []
        body_texts, header_texts, footer_texts = [], [], []

        for b in blocks:
            x0, by0, x1, by1, txt, *_ = b
            if not txt or not txt.strip():
                continue
            cy = (by0 + by1) / 2.0
            if cy < y0:
                header_texts.append(txt)
            elif cy > y1:
                footer_texts.append(txt)
            else:
                body_texts.append(txt)

        pages.append(
            {
                "page_no": i + 1,
                "text_raw": "\n".join(body_texts),
                "header_raw": "\n".join(header_texts),
                "footer_raw": "\n".join(footer_texts),
            }
        )
    return pages


RE_SPACES = re.compile(r"\s+")
RE_PUNCT_STRIP = re.compile(r"[^\w\u4e00-\u9fff\u3400-\u4dbf]+", flags=re.UNICODE)


def canon_line_for_template(line: str) -> str:
    t = (line or "").strip()
    if not t:
        return ""
    low = nfkc(t).lower()
    low = re.sub(r"\d", "#", low)
    low = re.sub(r"https?://\S+", " URL ", low)
    low = re.sub(r"\bwww\.\S+", " URL ", low)
    low = RE_SPACES.sub(" ", low).strip()
    low2 = RE_PUNCT_STRIP.sub(" ", low)
    low2 = RE_SPACES.sub(" ", low2).strip()
    return low2


def is_very_short_or_junk(line: str) -> bool:
    t = (line or "").strip()
    if not t:
        return True
    if re.fullmatch(r"[-–—_.,\s]{6,}", t):
        return True
    if re.fullmatch(r"[-–— ]*\d{1,4}[-–— ]*", t):
        return True
    return False


def compute_repeated_templates_from_zones(pages, min_frac=0.45):
    if not pages:
        return set()

    n_pages = len(pages)
    need = max(2, int(n_pages * min_frac))
    counter = Counter()

    for pg in pages:
        zone_text = (pg.get("header_raw") or "") + "\n" + (pg.get("footer_raw") or "")
        lines = [ln.strip() for ln in zone_text.splitlines() if ln.strip()]
        seen = set()
        for ln in lines:
            if is_very_short_or_junk(ln):
                continue
            c = canon_line_for_template(ln)
            if not c:
                continue
            if c in seen:
                continue
            seen.add(c)
            counter[c] += 1

    templates = {c for c, k in counter.items() if k >= need}
    refined = set()
    for c in templates:
        if len(c) <= 160 or "url" in c:
            refined.add(c)
    return refined


def strip_templates_from_text(page_text_raw: str, templates: set[str]) -> str:
    lines = [ln.rstrip() for ln in (page_text_raw or "").splitlines()]
    kept = []
    for ln in lines:
        t = ln.strip()
        if not t:
            continue
        c = canon_line_for_template(t)
        if c and c in templates:
            continue
        kept.append(ln)
    return "\n".join(kept)


def prepare_pages(pdf_path: Path, header_frac=0.12, footer_frac=0.12):
    pages = read_pages_body(pdf_path, header_frac=header_frac, footer_frac=footer_frac)
    templates = compute_repeated_templates_from_zones(pages, min_frac=0.45)
    out = []
    for pg in pages:
        txt = strip_templates_from_text(pg["text_raw"], templates)
        out.append({"page_no": pg["page_no"], "text": normalize_text(txt)})
    return out


# ----------------------------
# Chinese ref segmentation + merging + filtering
# ----------------------------
RE_ZH_PAGE_XY = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")
RE_ZH_VERSION = re.compile(
    r"(最后更新时间|数据最后更新时间|版本自.*生效|版本.*生效|自\d{4}年\d{1,2}月\d{1,2}日起生效|修订|修改|更新)",
    re.IGNORECASE,
)
RE_ZH_ART = re.compile(r"(第\s*[0-9一二三四五六七八九十百千]+\s*条)")
RE_ZH_TITLE = re.compile(r"^(标题|第[一二三四五六七八九十]+章|第[一二三四五六七八九十]+节)\s*[:：]", re.IGNORECASE)
RE_ZH_PAREN_ONLY = re.compile(r"^[（(].*[)）]$")


def is_zh_noise_line(ln: str) -> bool:
    t = (ln or "").strip()
    if not t:
        return True
    if RE_ZH_PAGE_XY.match(t):
        return True
    if RE_ZH_VERSION.search(t):
        return True
    if len(t) <= 4 and re.fullmatch(r"[\d/—\-–\s]+", t):
        return True
    return False


def split_zh_ref_page_into_segments(text: str) -> list[str]:
    t = normalize_text(text or "")
    if not t:
        return []

    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    kept = []
    for ln in lines:
        if is_zh_noise_line(ln):
            continue
        kept.append(ln)
    t = "\n".join(kept)
    if not t:
        return []

    t = RE_ZH_ART.sub(r"\n\n\1", t)
    t = re.sub(r"\n(?=(标题|第[一二三四五六七八九十]+章|第[一二三四五六七八九十]+节)\b)", "\n\n", t)

    paras = [p.strip() for p in re.split(r"\n{2,}", t) if p.strip()]

    segs = []
    for p in paras:
        if RE_ZH_TITLE.match(p) and len(p) <= 60:
            segs.append(p)
            continue

        sents = re.split(r"(?<=[。！？；])\s*", p)
        for s in sents:
            s = s.strip()
            if not s:
                continue
            if len(s) < 8 and not RE_ZH_ART.search(s):
                continue
            segs.append(s)

    return segs


def merge_zh_segments(segs: list[str]) -> list[str]:
    if not segs:
        return []

    out = []
    i = 0
    while i < len(segs):
        cur = segs[i].strip()
        if not cur:
            i += 1
            continue

        if (RE_ZH_TITLE.match(cur) and len(cur) <= 80) or (RE_ZH_PAREN_ONLY.match(cur) and len(cur) <= 60):
            merged = cur
            j = i + 1

            for _ in range(3):
                if j >= len(segs):
                    break
                nxt = segs[j].strip()
                if not nxt:
                    j += 1
                    continue

                if RE_ZH_PAREN_ONLY.match(nxt) and len(nxt) <= 80:
                    merged += " " + nxt
                    j += 1
                    continue

                if len(nxt) >= 12:
                    merged += " " + nxt
                    j += 1
                break

            out.append(collapse_pdf_linebreaks(merged))
            i = j
            continue

        if RE_ZH_ART.fullmatch(cur) and i + 1 < len(segs):
            nxt = segs[i + 1].strip()
            out.append(collapse_pdf_linebreaks(cur + " " + nxt))
            i += 2
            continue

        out.append(collapse_pdf_linebreaks(cur))
        i += 1

    out2 = []
    for s in out:
        if not s:
            continue
        if len(s) < 6 and not RE_ZH_ART.search(s):
            continue
        out2.append(s)
    return out2


# ---- Strong garbage filtering (TOC / cover approvals / numbered lists / table fragments)
RE_TOC_HINT = re.compile(r"(目录|目\s*录|table\s+of\s+contents|contents|页码)", re.IGNORECASE)
RE_APPROVAL_HINT = re.compile(r"(提供方|审查人|确认人|批准人|签发|局长|副局长|主任|日期\s*[:：])")
RE_DOTS_LEADER = re.compile(r"[·•\.]{3,}")               # ..... or ……
RE_ONLY_SYMBOLS = re.compile(r"^[\W_]+$", re.UNICODE)

# numbered items: "1." "2." "4.1" "4.2" "10.3.1" etc
RE_NUM_ITEM = re.compile(r"(?<!\d)(\d{1,2}(?:\.\d{1,2}){0,3})\s*[\.、)]")
RE_SECTION_NUM = re.compile(r"(?<!\d)\d{1,2}(?:\.\d{1,2}){1,3}(?!\d)")  # 4.1 / 4.12.3


def digit_ratio(s: str) -> float:
    if not s:
        return 1.0
    digits = sum(ch.isdigit() for ch in s)
    return digits / max(1, len(s))


def punct_ratio(s: str) -> float:
    if not s:
        return 1.0
    punct = 0
    for ch in s:
        cat = unicodedata.category(ch)
        if cat.startswith("P") or cat.startswith("S"):
            punct += 1
    return punct / max(1, len(s))


def count_numbered_markers(s: str) -> int:
    t = s or ""
    return len(RE_NUM_ITEM.findall(t)) + len(RE_SECTION_NUM.findall(t))


def looks_like_toc_or_list_blob(t: str) -> bool:
    """
    JPJ/standards often have a long blob like:
    '编号 目录 页码 1. 简介 2. 参考法律 3. ... 4.1 ... 4.2 ...'
    If numbered markers are dense, treat as TOC/list noise.
    """
    if len(t) < 80:
        return False
    c = count_numbered_markers(t)
    # threshold: adjust to be aggressive on JPJ-style pages
    return c >= 6


def is_zh_garbage_segment(seg: str) -> bool:
    t = (seg or "").strip()
    if not t:
        return True

    if RE_ONLY_SYMBOLS.match(t):
        return True

    # very short
    if len(t) < 10 and not RE_ZH_ART.search(t):
        return True

    # approval/signature cover patterns
    if RE_APPROVAL_HINT.search(t) and len(t) > 60:
        return True

    # TOC / list blob patterns (strong)
    if RE_TOC_HINT.search(t):
        if RE_DOTS_LEADER.search(t):
            return True
        if looks_like_toc_or_list_blob(t):
            return True

    # Even without explicit "目录"，dense numbered lists are usually not aligned content
    if looks_like_toc_or_list_blob(t):
        return True

    # table-like: too many digits or punct/symbols
    if digit_ratio(t) > 0.35 and len(t) > 30:
        return True
    if punct_ratio(t) > 0.40 and len(t) > 30:
        return True

    return False


def build_ref_units_from_pdf(ref_pdf: Path, header_frac=0.12, footer_frac=0.12):
    pages = prepare_pages(ref_pdf, header_frac=header_frac, footer_frac=footer_frac)

    segs = []
    seg_page = []
    for pg in pages:
        s = split_zh_ref_page_into_segments(pg.get("text", ""))
        s = merge_zh_segments(s)

        for x in s:
            x = collapse_pdf_linebreaks(x)
            if is_zh_garbage_segment(x):
                continue
            segs.append(x)
            seg_page.append(pg["page_no"])

    return [{"text": segs[i], "page_no": seg_page[i]} for i in range(len(segs))]


# ----------------------------
# Embeddings + caching
# ----------------------------
def embed_texts(model, texts: list[str], batch_size=64) -> np.ndarray:
    emb = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(emb, dtype=np.float32)


def load_or_compute_embeddings(cache_dir: Path, key: str, compute_fn):
    ensure_dir(cache_dir)
    path = cache_dir / f"{key}.npy"
    if path.exists():
        return np.load(path)
    arr = compute_fn()
    np.save(path, arr)
    return arr


def cosine_sim_matrix(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    return A @ B.T


# ----------------------------
# Monotonic DP alignment (semantic)
# ----------------------------
def align_monotonic_semantic(sim: np.ndarray,
                             w11=1.0, w12=0.95, w21=0.95,
                             skip_ref_pen=0.20, skip_src_pen=0.35):
    n, m = sim.shape
    NEG = -1e9

    dp = np.full((n + 1, m + 1), NEG, dtype=np.float32)
    bp = np.empty((n + 1, m + 1), dtype=object)
    dp[0, 0] = 0.0
    bp[0, 0] = None

    def upd(i2, j2, val, back):
        if val > dp[i2, j2]:
            dp[i2, j2] = val
            bp[i2, j2] = back

    for i in range(n + 1):
        for j in range(m + 1):
            base = float(dp[i, j])
            if base <= NEG / 2:
                continue

            # skip ref
            if j < m:
                upd(i, j + 1, base - skip_ref_pen, (i, j, "0-1"))

            # skip src
            if i < n:
                upd(i + 1, j, base - skip_src_pen, (i, j, "1-0"))

            # 1-1
            if i < n and j < m:
                upd(i + 1, j + 1, base + w11 * float(sim[i, j]), (i, j, "1-1"))

            # 1-2
            if i < n and (j + 1) < m:
                s = 0.5 * (float(sim[i, j]) + float(sim[i, j + 1]))
                upd(i + 1, j + 2, base + w12 * s, (i, j, "1-2"))

            # 2-1
            if (i + 1) < n and j < m:
                s = 0.5 * (float(sim[i, j]) + float(sim[i + 1, j]))
                upd(i + 2, j + 1, base + w21 * s, (i, j, "2-1"))

    # backtrack
    i, j = n, m
    path = []
    while True:
        b = bp[i, j]
        if b is None:
            break
        pi, pj, kind = b

        if kind == "1-1":
            local = float(sim[pi, pj])
            path.append((pi, i, pj, j, "1-1", local))
        elif kind == "1-2":
            local = float(0.5 * (sim[pi, pj] + sim[pi, pj + 1]))
            path.append((pi, i, pj, j, "1-2", local))
        elif kind == "2-1":
            local = float(0.5 * (sim[pi, pj] + sim[pi + 1, pj]))
            path.append((pi, i, pj, j, "2-1", local))
        elif kind == "0-1":
            path.append((pi, i, pj, j, "0-1", 0.0))
        elif kind == "1-0":
            path.append((pi, i, pj, j, "1-0", 0.0))
        else:
            raise ValueError(f"Unknown kind: {kind}")

        i, j = pi, pj

    path.reverse()
    return path, float(dp[n, m])


# ----------------------------
# Pairing src <-> ref pdf by filename
# ----------------------------
def guess_ref_pdf_for_src(src_jsonl: Path, raw_dir: Path) -> Path:
    name = src_jsonl.name
    m = re.match(r"^(?P<prefix>.+?)_src_[a-z]{2}\.sent\d+\.jsonl$", name, flags=re.IGNORECASE)
    if m:
        prefix = m.group("prefix")
    else:
        prefix = re.sub(r"\.sent\d+\.jsonl$", "", name, flags=re.IGNORECASE)
        prefix = re.sub(r"_src_[a-z]{2}$", "", prefix, flags=re.IGNORECASE)
    return raw_dir / f"{prefix}_ref_zh.pdf"


# ----------------------------
# Alignment for one file
# ----------------------------
def align_one(src_jsonl: Path,
              raw_dir: Path,
              out_dir: Path,
              model: SentenceTransformer,
              cache_dir: Path,
              batch_size=64,
              header_frac=0.12,
              footer_frac=0.12,
              w11=1.0, w12=0.95, w21=0.95,
              skip_ref_pen=0.18, skip_src_pen=0.35):
    src_rows = read_jsonl(src_jsonl)
    src_texts = [normalize_text(r.get("text", "")) for r in src_rows]

    ref_pdf = guess_ref_pdf_for_src(src_jsonl, raw_dir)
    if not ref_pdf.exists():
        raise FileNotFoundError(f"Ref PDF not found for {src_jsonl.name}: {ref_pdf}")

    ref_units = build_ref_units_from_pdf(ref_pdf, header_frac=header_frac, footer_frac=footer_frac)
    ref_texts = [u["text"] for u in ref_units]

    if not src_texts:
        raise ValueError(f"No src texts in {src_jsonl}")
    if not ref_texts:
        raise ValueError(f"No ref segments extracted from {ref_pdf}. PDF might be scanned or extraction failed.")

    # embedding cache keys (depend on content)
    src_key = f"src_{src_jsonl.stem}_{sha1_text_list(src_texts)}"
    ref_key = f"ref_{ref_pdf.stem}_{sha1_text_list(ref_texts)}"

    E_src = load_or_compute_embeddings(
        cache_dir, src_key,
        lambda: embed_texts(model, src_texts, batch_size=batch_size)
    )
    E_ref = load_or_compute_embeddings(
        cache_dir, ref_key,
        lambda: embed_texts(model, ref_texts, batch_size=batch_size)
    )

    sim = cosine_sim_matrix(E_src, E_ref)

    path, total = align_monotonic_semantic(
        sim,
        w11=w11, w12=w12, w21=w21,
        skip_ref_pen=skip_ref_pen,
        skip_src_pen=skip_src_pen
    )

    src_to_ref = {i: None for i in range(len(src_rows))}
    for (i0, i1, j0, j1, kind, local_score) in path:
        if kind in ("1-1", "1-2", "2-1"):
            for i in range(i0, i1):
                src_to_ref[i] = (j0, j1, kind, float(local_score))
        elif kind == "1-0":
            for i in range(i0, i1):
                src_to_ref[i] = None

    out_rows = []
    for i, r in enumerate(src_rows):
        item = dict(r)
        m = src_to_ref.get(i)

        if not m:
            item["ref_text"] = ""
            item["ref_page_no"] = None
            item["align_span"] = {"src": [i, i + 1], "ref": None, "kind": "1-0"}
            item["align_score"] = 0.0
        else:
            j0, j1, kind, local = m
            ref_join = " ".join(ref_texts[j0:j1]).strip()
            ref_page = ref_units[j0]["page_no"] if 0 <= j0 < len(ref_units) else None

            item["ref_text"] = ref_join
            item["ref_page_no"] = ref_page
            item["align_span"] = {"src": [i, i + 1], "ref": [j0, j1], "kind": kind}
            item["align_score"] = float(local)

        item["ref_doc"] = ref_pdf.name
        out_rows.append(item)

    out_path = out_dir / src_jsonl.name.replace(".jsonl", ".da.jsonl")
    write_jsonl(out_path, out_rows)

    scores = [x.get("align_score", 0.0) for x in out_rows]
    p50 = float(np.percentile(scores, 50))
    p10 = float(np.percentile(scores, 10))
    p90 = float(np.percentile(scores, 90))

    return {
        "src": str(src_jsonl),
        "ref": str(ref_pdf),
        "out": str(out_path),
        "n_src": len(src_rows),
        "n_ref_units": len(ref_units),
        "dp_total": float(total),
        "score_p10": p10,
        "score_p50": p50,
        "score_p90": p90,
    }


# ----------------------------
# CLI
# ----------------------------
def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--src_jsonl", type=str, help="Single src jsonl file (*.sent*.jsonl)")
    g.add_argument("--eval_dir", type=str, help="Directory containing src jsonl files")

    ap.add_argument("--raw_dir", type=str, required=True, help="Directory containing *_ref_zh.pdf")
    ap.add_argument("--out_dir", type=str, required=True, help="Output directory for *.da.jsonl")
    ap.add_argument("--cache_dir", type=str, default=None, help="Embedding cache dir (default: out_dir/.emb_cache)")

    ap.add_argument("--model", type=str, default="sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
    ap.add_argument("--batch_size", type=int, default=64)

    # Default back to safer cropping
    ap.add_argument("--header_frac", type=float, default=0.12)
    ap.add_argument("--footer_frac", type=float, default=0.12)

    ap.add_argument("--w11", type=float, default=1.0)
    ap.add_argument("--w12", type=float, default=0.95)
    ap.add_argument("--w21", type=float, default=0.95)
    ap.add_argument("--skip_ref_pen", type=float, default=0.18)
    ap.add_argument("--skip_src_pen", type=float, default=0.35)

    ap.add_argument("--skip_existing", action="store_true", help="Skip if output .da.jsonl already exists")
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)

    cache_dir = Path(args.cache_dir) if args.cache_dir else (out_dir / ".emb_cache")
    ensure_dir(cache_dir)

    model = SentenceTransformer(args.model)

    reports = []
    if args.src_jsonl:
        rep = align_one(
            Path(args.src_jsonl),
            raw_dir=raw_dir,
            out_dir=out_dir,
            model=model,
            cache_dir=cache_dir,
            batch_size=args.batch_size,
            header_frac=args.header_frac,
            footer_frac=args.footer_frac,
            w11=args.w11, w12=args.w12, w21=args.w21,
            skip_ref_pen=args.skip_ref_pen,
            skip_src_pen=args.skip_src_pen,
        )
        reports.append(rep)
    else:
        eval_dir = Path(args.eval_dir)
        files = sorted(eval_dir.glob("*.sent*.jsonl"))
        if not files:
            raise FileNotFoundError(f"No *.sent*.jsonl found in {eval_dir}")

        for f in files:
            if f.name.endswith(".da.jsonl"):
                continue
            out_path = out_dir / f.name.replace(".jsonl", ".da.jsonl")
            if args.skip_existing and out_path.exists():
                continue

            rep = align_one(
                f,
                raw_dir=raw_dir,
                out_dir=out_dir,
                model=model,
                cache_dir=cache_dir,
                batch_size=args.batch_size,
                header_frac=args.header_frac,
                footer_frac=args.footer_frac,
                w11=args.w11, w12=args.w12, w21=args.w21,
                skip_ref_pen=args.skip_ref_pen,
                skip_src_pen=args.skip_src_pen,
            )
            reports.append(rep)

    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
