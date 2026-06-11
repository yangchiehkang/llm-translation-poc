# sent_split_batch.py  (Part 1/3)
# -*- coding: utf-8 -*-

import re
import json
import math
import random
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from collections import Counter, defaultdict

import fitz  # PyMuPDF


# ============================================================
# Language & filename conventions
# ============================================================

# We support languages shown in your screenshot:
# ar, nl, en, fr, de, id, it, ms, no, pt, ru, es, sv, th, vi
SUPPORTED_LANGS = {
    "ar", "nl", "en", "fr", "de", "id", "it", "ms", "no", "pt", "ru", "es", "sv", "th", "vi"
}

# Typical filenames:
#   arabic_src_ar.pdf
#   dutch_src_nl.pdf
#   portuguese_src_pt.pdf
# We detect lang from the last token before ".pdf": *_src_{lang}.pdf
SRC_FILE_LANG_RE = re.compile(r"_src_([a-z]{2})\.pdf$", flags=re.IGNORECASE)

# Optional: map common “name prefix” to language (not required, but helps logging)
PREFIX_HINTS = {
    "arabic": "ar",
    "dutch": "nl",
    "english": "en",
    "french": "fr",
    "german": "de",
    "indonesian": "id",
    "italian": "it",
    "malay": "ms",
    "norwegian": "no",
    "portuguese": "pt",
    "russian": "ru",
    "spanish": "es",
    "swedish": "sv",
    "thai": "th",
    "vietnamese": "vi",
}


def detect_lang_from_filename(p: Path) -> str | None:
    m = SRC_FILE_LANG_RE.search(p.name)
    if not m:
        return None
    lang = m.group(1).lower()
    return lang if lang in SUPPORTED_LANGS else None


# ============================================================
# IO utils
# ============================================================

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def write_jsonl(path: Path, rows):
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ============================================================
# Text normalization
# ============================================================

ARABIC_TATWEEL = "\u0640"

AR_PUNCT_MAP = {
    ",": "،",
    ";": "؛",
    "?": "؟",
}

AR_DIGIT_MAP = str.maketrans({
    # Eastern Arabic digits (Persian) -> Arabic-Indic
    "۰": "٠", "۱": "١", "۲": "٢", "۳": "٣", "۴": "٤",
    "۵": "٥", "۶": "٦", "۷": "٧", "۸": "٨", "۹": "٩",
})


def nfkc(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s)


def norm_ws(s: str) -> str:
    """Whitespace normalization + remove common hidden chars."""
    if not s:
        return ""
    s = s.replace("\u00ad", "").replace("\ufeff", "")  # soft-hyphen, BOM
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def normalize_arabic_text(s: str) -> str:
    """
    Light Arabic normalization to stabilize segmentation:
    - NFKC
    - remove tatweel
    - unify punctuation into Arabic equivalents
    - unify Persian digits -> Arabic-Indic
    """
    if not s:
        return ""
    t = nfkc(s)
    t = t.replace(ARABIC_TATWEEL, "")
    for k, v in AR_PUNCT_MAP.items():
        t = t.replace(k, v)
    t = t.translate(AR_DIGIT_MAP)
    return norm_ws(t)


def normalize_by_lang(s: str, lang: str) -> str:
    if not s:
        return ""
    if lang == "ar":
        return normalize_arabic_text(s)
    # Thai/Vietnamese etc: keep simple NFKC + whitespace normalization
    return norm_ws(nfkc(s))


# ============================================================
# PDF read (body-only by coordinates)
# ============================================================

@dataclass
class PageBlocks:
    page_no: int
    text_raw: str
    header_raw: str
    footer_raw: str


def read_pages_body(pdf_path: Path, header_frac=0.12, footer_frac=0.12) -> list[PageBlocks]:
    """
    Read PDF blocks and keep only middle "body" region by y-coordinates.
    This removes most headers/footers at source.
    """
    doc = fitz.open(str(pdf_path))
    pages: list[PageBlocks] = []

    for i in range(len(doc)):
        page = doc[i]
        H = page.rect.height
        y0 = H * header_frac
        y1 = H * (1 - footer_frac)

        blocks = page.get_text("blocks") or []
        body_texts, header_texts, footer_texts = [], [], []

        for b in blocks:
            x0, by0, x1, by1, txt, *_ = b
            if not txt or not txt.strip():
                continue
            cy = (by0 + by1) / 2
            if cy < y0:
                header_texts.append(txt)
            elif cy > y1:
                footer_texts.append(txt)
            else:
                body_texts.append(txt)

        pages.append(PageBlocks(
            page_no=i + 1,
            text_raw="\n".join(body_texts),
            header_raw="\n".join(header_texts),
            footer_raw="\n".join(footer_texts),
        ))

    return pages


# ============================================================
# Repeated template stripping (from header/footer zones only)
# ============================================================

RE_SPACES = re.compile(r"\s+")

# Keep word chars + scripts we care about (Latin, Arabic, Thai, Cyrillic, Vietnamese still mostly Latin)
RE_PUNCT_STRIP = re.compile(r"[^\w\u0600-\u06FF\u0E00-\u0E7F\u0400-\u04FF\u00C0-\u024F]+", flags=re.UNICODE)


def canon_line_for_template(line: str) -> str:
    """
    Canonicalize a header/footer line to detect repeated templates across pages.
    - lowercase
    - mask digits (Latin, Arabic-Indic, Thai)
    - normalize URLs
    - strip punctuation differences
    """
    t = (line or "").strip()
    if not t:
        return ""

    low = nfkc(t).lower()

    # mask digits
    low = re.sub(r"\d", "#", low)
    low = re.sub(r"[٠-٩]", "#", low)
    low = re.sub(r"[๐-๙]", "#", low)

    # normalize URL patterns
    low = re.sub(r"https?://\S+", " URL ", low)
    low = re.sub(r"\bwww\.\S+", " URL ", low)

    low = RE_SPACES.sub(" ", low).strip()

    # remove punctuation differences
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


def compute_repeated_templates_from_zones(pages: list[PageBlocks], min_frac=0.45) -> set[str]:
    """
    Count canonicalized lines from header/footer zones.
    If a line appears in >= min_frac pages, treat it as a template and remove it.
    """
    if not pages:
        return set()

    n_pages = len(pages)
    need = max(2, int(n_pages * min_frac))
    counter = Counter()

    for pg in pages:
        zone_text = (pg.header_raw or "") + "\n" + (pg.footer_raw or "")
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

    # refine: avoid huge template strings swallowing body
    refined = set()
    for c in templates:
        if len(c) <= 200:
            refined.add(c)
        elif "url" in c:
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


def prepare_pages(pdf_path: Path, lang: str, header_frac=0.12, footer_frac=0.12, min_template_frac=0.45):
    """
    Return list of dict pages: {page_no, text}
    - body-only extraction
    - repeated header/footer template stripping
    - language normalization
    """
    pages = read_pages_body(pdf_path, header_frac=header_frac, footer_frac=footer_frac)
    templates = compute_repeated_templates_from_zones(pages, min_frac=min_template_frac)

    out = []
    for pg in pages:
        txt = strip_templates_from_text(pg.text_raw, templates)
        out.append({
            "page_no": pg.page_no,
            "text": normalize_by_lang(txt, lang),
        })
    return out


# ============================================================
# TOC / outline detection (page-level)
# ============================================================

RE_NUM_DOTTED = re.compile(r"\b\d+(?:\.\d+){1,3}\b")
RE_ROMANS = re.compile(r"\b[IVXLC]{1,6}\.\b")
RE_DOT_LEADER = re.compile(r"\.{2,}")
RE_SECTION_MARK = re.compile(r"§\s*\d{1,4}")

RE_ARABIC_INDIC_NUM = re.compile(r"[٠-٩]{1,4}")
RE_AR_MADDA = re.compile(r"(?:المادة)\s*[\(\[]?\s*[٠-٩0-9]{1,4}\s*[\)\]]?")

def looks_like_toc_outline(text: str, lang: str) -> bool:
    t = normalize_by_lang(text or "", lang)
    if len(t) < 30:
        return False

    dotted = len(RE_NUM_DOTTED.findall(t))
    romans = len(RE_ROMANS.findall(t))
    sect = len(RE_SECTION_MARK.findall(t))
    has_dots = bool(RE_DOT_LEADER.search(t))

    if lang == "ar":
        # Arabic TOC often contains many "المادة (رقم)"
        if ("المحتويات" in t) or ("الفهرس" in t) or ("من المحتويات" in t):
            if len(RE_AR_MADDA.findall(t)) >= 6:
                return True
        if len(RE_AR_MADDA.findall(t)) >= 12:
            return True

    if lang == "th":
        if "สารบัญ" in t:
            return True
        if len(re.findall(r"มาตรา\s*\d+", t)) >= 12:
            return True

    if has_dots and (dotted + romans + sect >= 3):
        return True

    punct = len(re.findall(r"[。！？!?;:؟،؛]", t))
    token_score = 2.0 * dotted + 2.0 * romans + 2.0 * sect
    if token_score >= 16 and punct <= 1:
        return True

    return False


def is_toc_like_page(page_text: str, lang: str) -> bool:
    txt = normalize_by_lang(page_text or "", lang)
    if not txt:
        return True

    low = txt.lower()
    # Multi-language TOC keywords
    if any(k in low for k in [
        "table of contents", "contents",
        "inhaltsverzeichnis", "inhaltsübersicht", "inhaltsuebersicht",
        "содержание", "оглавление",
        "isi kandungan",
        "table des matières", "table des matieres", "sommaire",
        "índice", "indice", "sumário", "sumario", "conteúdo", "conteudo",
        "inhoud", "inhoudsopgave", "register",
        "innehåll", "innehall", "innehållsförteckning", "innehallsforteckning",
        "innhold", "innholdsfortegnelse", "innhald",
    ]):
        return True

    if lang == "ar" and (("المحتويات" in txt) or ("الفهرس" in txt) or ("من المحتويات" in txt)):
        return True
    if lang == "th" and "สารบัญ" in txt:
        return True

    return looks_like_toc_outline(txt, lang)

# sent_split_batch.py  (Part 2/3)
# -*- coding: utf-8 -*-

# ============================================================
# Cover / preamble detection + start-page selection
# Sentence splitting helpers (mask/unmask + merge wrapped lines)
# ============================================================

# ---- Cover/preamble helpers ----

def uppercase_ratio_latin(text: str) -> float:
    t = text or ""
    letters = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿА-ЯЁа-яёÄÖÜäöüß]", t)
    if not letters:
        return 0.0
    uppers = re.findall(r"[A-ZÀ-ÖØ-ÞА-ЯЁÄÖÜẞ]", t)
    return len(uppers) / max(1, len(letters))


def latin_ratio(text: str) -> float:
    t = text or ""
    letters = re.findall(r"[A-Za-z]", t)
    any_letters = re.findall(r"[A-Za-zА-ЯЁа-яё]", t)
    if not any_letters:
        return 0.0
    return len(letters) / max(1, len(any_letters))


# Preamble patterns (mainly useful for FR/ES legal decrees)
PREAMBLE_HINTS = {
    "es": [
        r"^VISTO\b", r"^Visto\b",
        r"^CONSIDERANDO\b", r"^Considerando\b",
        r"^DECRETA\b", r"^DECRETO\b", r"^Decreto\b",
    ],
    "fr": [
        r"^Vu\b", r"^VU\b",
        r"^Consid[ée]rant\b",
        r"^ARR[ÊE]T[ÉE]\b",
        r"^D[ÉE]CRET\b",
        r"\bJournal officiel\b",
    ],
}

# Some langs we want stricter "legal text start" (avoid preamble-heavy pages)
STRICT_LEGAL_START_LANGS = {"fr", "es", "de", "ar", "th"}

# For some langs, we require "Article/Artículo" presence to consider it as real body start
ARTICLE_START_REQUIRED = {"fr", "es"}
ARTICLE_START_PAT = {
    "fr": re.compile(r"\bArticle\s*\d+\b", flags=re.IGNORECASE),
    "es": re.compile(r"\bArtículo\s*\d+\b", flags=re.IGNORECASE),
}


def has_required_article_start(text: str, lang: str) -> bool:
    if lang not in ARTICLE_START_REQUIRED:
        return True
    t = normalize_by_lang(text or "", lang)
    return bool(ARTICLE_START_PAT[lang].search(t))


def is_preamble_like_page(text: str, lang: str) -> bool:
    t = normalize_by_lang(text or "", lang)
    if not t:
        return True
    if lang not in PREAMBLE_HINTS:
        return False

    # If we already have an "Article" start, treat as body, not preamble.
    if has_required_article_start(t, lang):
        return False

    hits = 0
    for p in PREAMBLE_HINTS[lang]:
        if re.search(p, t, flags=re.IGNORECASE | re.MULTILINE):
            hits += 1

    strong_punct = len(re.findall(r"[\.!\?\u061F。！？]", t))
    colon = t.count(":")
    if hits >= 1 and strong_punct <= 10 and colon >= 1:
        return True
    if hits >= 2 and len(t) < 2500:
        return True

    return False


# RU cover hints (common for GOST/ISO cover pages)
RU_COVER_HINTS = [
    r"\binterstate council\b",
    r"\bfor standardization\b",
    r"\bmetrology\b",
    r"\bcertification\b",
    r"\binternational standard\b",
    r"\bics\b",
    r"\budc\b",
    r"\biso\b",
    r"\biec\b",
    r"\ben\s*\d{3,}\b",

    r"\bмежгосударственн",
    r"\bгосударственн(ый|ое)\s+стандарт\b",
    r"\bгост\b",
    r"\bиздание\s+официальное\b",
    r"\bофициальное\s+издание\b",
    r"\bмосква\b",
    r"\bстандартинформ\b",
    r"\bутвержден\b",
    r"\bвведен(о|)\s+в\s+действие\b",
    r"\bвзамен\b",
    r"\bнастоящ(ий|ее)\s+стандарт\b",
]


def is_ru_cover_like(text: str) -> bool:
    t = nfkc(norm_ws(text or ""))
    if not t:
        return True

    # If it already contains anchors (sections), it's likely body, not cover
    if anchor_hit_count(t, "ru") >= 1:
        return False

    low = t.lower()

    hint_hits = 0
    for pat in RU_COVER_HINTS:
        if re.search(pat, low, flags=re.IGNORECASE):
            hint_hits += 1
            if hint_hits >= 2:
                return True

    lat_r = latin_ratio(t)
    up_r = uppercase_ratio_latin(t)
    strong_punct = len(re.findall(r"[\.!\?\u061F。！？]", t))
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    short_lines = sum(1 for ln in lines if len(ln) <= 55)

    if lat_r >= 0.55 and up_r >= 0.55 and strong_punct <= 1 and short_lines >= 5 and len(t) < 3000:
        return True

    if re.search(r"\bгост\b", low) and strong_punct <= 2:
        return True

    return False


# ---- Anchors (language-specific “body starts here” cues) ----

ANCHORS = {
    "es": [r"\bArtículo\s*\d+\b", r"^T[ÍI]TULO\b", r"^CAP[IÍ]TULO\b"],
    "fr": [r"\bArticle\s*\d+\b", r"^TITRE\b", r"^CHAPITRE\b"],
    "de": [r"^§\s*\d+", r"\bArtikel\s*\d+\b", r"\bAbschnitt\b"],
    "ar": [r"\bالمادة\b", r"\bالباب\b", r"\bالفصل\b"],
    "th": [r"\bมาตรา\b", r"^ข้อ\s*\d+", r"\bบท\b", r"\bหมวด\b"],
    "en": [r"\bScope\b", r"\bTerms and definitions\b", r"\bForeword\b", r"\b1\.\s"],
    "ru": [
        r"\bПредисловие\b",
        r"\bВведение\b",
        r"\bОбласть применения\b",
        r"\bНормативные ссылки\b",
        r"\bТермины\b",
        r"\bОпределения\b",
        r"\b1\.\s",
        r"\bРаздел\b",
        r"\bПриложение\b",
    ],
    "ms": [r"\bPENGENALAN\b", r"\bBAHAGIAN\b", r"\b1\.\s"],
    "id": [r"\bBAB\b", r"\bPasal\b", r"\bBagian\b", r"\bParagraf\b"],
    "it": [r"\bArticolo\s*\d+\b", r"\bArt\.\s*\d+\b", r"^TITOLO\b", r"^CAPO\b"],
    "pt": [r"\bArtigo\s*\d+\b", r"^T[IÍ]TULO\b", r"^CAP[IÍ]TULO\b", r"^SE[CÇ][AÃ]O\b"],
    "nl": [r"\bArtikel\s*\d+\b", r"^Hoofdstuk\b", r"^Afdeling\b", r"^§\s*\d+"],
    "no": [r"^§\s*\d+", r"\bKapittel\s*\d+\b", r"^Kapittel\b", r"^Avsnitt\b"],
    "sv": [r"^§\s*\d+", r"\bKapitel\s*\d+\b", r"^Kapitel\b", r"^Avsnitt\b"],
    "vi": [r"\bĐiều\s*\d+\b", r"\bChương\s*\d+\b", r"^CHƯƠNG\b", r"^ĐIỀU\b"],
}

IT_ART_ANCHOR = re.compile(r"\b(Art\.\s*\d+|Articolo\s*\d+)\b", flags=re.IGNORECASE)


def anchor_hit_count(text: str, lang: str) -> int:
    t = normalize_by_lang(text or "", lang)
    pats = [re.compile(p, flags=re.IGNORECASE | re.MULTILINE) for p in ANCHORS.get(lang, [])]
    return sum(1 for p in pats if p.search(t))


def page_body_density_score(text: str, lang: str) -> float:
    """
    A simple heuristic to pick the first “real body” page:
    - proportion of letters
    - punctuation density
    - penalize outline/TOC pages
    """
    t = normalize_by_lang(text or "", lang)
    if not t:
        return 0.0

    if lang == "ar":
        letters = len(re.findall(r"[ء-ي]", t))
    elif lang == "th":
        letters = len(re.findall(r"[ก-๙]", t))
    elif lang == "ru":
        letters = len(re.findall(r"[А-ЯЁа-яё]", t))
    else:
        letters = len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]", t))

    punct = len(re.findall(r"[\.!\?¿¡\u061F。！？;:؛،]", t))
    outline = len(RE_NUM_DOTTED.findall(t)) + len(RE_ROMANS.findall(t)) + len(RE_SECTION_MARK.findall(t))
    if lang == "ar":
        outline += len(RE_AR_MADDA.findall(t))

    L = max(1, len(t))
    score = (letters / L) * 2.0 + (punct / L) * 10.0 - outline * 0.05

    if is_toc_like_page(t, lang):
        score -= 2.0
    if is_cover_like_page(t, lang):
        score -= 1.4
    if is_preamble_like_page(t, lang):
        score -= 1.0

    return score


def is_cover_like_page(text: str, lang: str) -> bool:
    t = normalize_by_lang(text or "", lang)
    if not t:
        return True

    # If TOC-like, do not treat it as cover (handled separately)
    if is_toc_like_page(t, lang):
        return False

    if lang == "ru":
        return is_ru_cover_like(t)

    # If required article start exists, it's body-ish.
    if has_required_article_start(t, lang):
        return False

    # If anchor exists (for non-required langs), it's likely body-ish.
    if lang not in ARTICLE_START_REQUIRED and anchor_hit_count(t, lang) >= 1:
        return False

    strong_punct = len(re.findall(r"[\.!\?\u061F。！？]", t))
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    n_lines = len(lines)
    short_lines = sum(1 for ln in lines if len(ln) <= 45)
    u_ratio = uppercase_ratio_latin(t)

    # For AR/TH cover pages: often many short lines, minimal punctuation
    if lang in {"ar", "th"}:
        if strong_punct <= 1 and n_lines >= 6 and short_lines >= 5 and len(t) < 1800:
            return True
        return False

    # Generic Latin-script cover heuristic
    if strong_punct <= 1 and ((n_lines >= 8 and short_lines >= 6) or (u_ratio >= 0.65)) and len(t) < 2200:
        return True

    return False


def find_start_page(pages: list[dict], lang: str) -> int:
    """
    Pick a start page number (1-based) where we believe main body begins.
    Strategy:
    - skip TOC clusters
    - skip covers/preambles early on
    - look for anchors and/or density
    """
    if not pages:
        return 1

    N = len(pages)
    for idx, pg in enumerate(pages):
        txt = pg.get("text", "") or ""
        if not txt:
            continue

        # Skip TOC clusters: if 2 of next 3 pages look like TOC, continue
        win = pages[idx: min(N, idx + 3)]
        toc_cnt = sum(1 for w in win if is_toc_like_page(w.get("text", ""), lang))
        if toc_cnt >= 2:
            continue

        if is_toc_like_page(txt, lang):
            continue

        if idx <= 12 and (is_cover_like_page(txt, lang) or is_preamble_like_page(txt, lang)):
            continue

        dens = page_body_density_score(txt, lang)
        ah = anchor_hit_count(txt, lang)

        # Italian: prefer starting at first Art./Articolo if present
        if lang == "it" and not IT_ART_ANCHOR.search(txt):
            # allow density-only fallback later
            if dens < 0.25:
                continue

        if lang in STRICT_LEGAL_START_LANGS:
            # For strict langs: require anchors or strong density
            if ah >= 1 and dens >= 0.07:
                return pg["page_no"]
            if dens >= 0.28:
                return pg["page_no"]
        else:
            if ah >= 1 and dens >= 0.06:
                return pg["page_no"]
            if dens >= 0.22:
                return pg["page_no"]

    return 1


# ============================================================
# Sentence splitting helpers
# ============================================================

DOT_MASK = "§"   # decimals/dates like 3.500 or 17.07.2024
ABBR_MASK = "¤"  # abbreviation dots like e.g.

ABBR = {
    "es": ["Núm.", "Num.", "Nº.", "N°.", "No.", "Art.", "Arts.", "Sr.", "Sra.", "Dr.", "Dra.", "Ud.", "Uds.", "D.O.", "pág.", "pp.", "etc."],
    "en": ["Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sr.", "Jr.", "St.", "No.", "Art.", "Sec.", "Fig.", "Eq.", "e.g.", "i.e.", "vs.", "etc."],
    "de": ["z.B.", "bzw.", "u.a.", "u.U.", "vgl.", "Nr.", "Art.", "Abs.", "S.", "Dr.", "Prof.", "etc.", "v.", "V.", "gem.", "i.V.m.", "i. V. m.", "BGBl.", "Fn.", "Bek.", "Anl.", "Anh."],
    "ru": ["г.", "ул.", "д.", "рис.", "табл.", "т.е.", "т.д.", "и т.п.", "см.", "стр.", "№."],
    "ms": ["Dr.", "Prof.", "No.", "Art.", "Sek.", "Raj.", "ms.", "dll."],
    "fr": ["M.", "Mme.", "Mlle.", "Dr.", "Pr.", "No.", "n°", "nº", "Art.", "pp.", "p.", "etc."],
    "pt": ["n.º", "nº", "n.°", "n°", "art.", "arts.", "sr.", "sra.", "dr.", "dra.", "exmo.", "etc.", "pág.", "pp."],
    "it": ["n.", "art.", "artt.", "sig.", "sig.ra", "dott.", "prof.", "ecc.", "cfr.", "p.es."],
    "nl": ["d.w.z.", "m.a.w.", "bijv.", "o.a.", "t.a.v.", "nr.", "art.", "dr.", "prof.", "etc."],
    "no": ["nr.", "jf.", "bl.a.", "m.m.", "osv.", "etc."],
    "sv": ["nr.", "jfr.", "bl.a.", "m.m.", "osv.", "etc."],
    "ar": [],
    "th": [],
    "id": ["no.", "dr.", "prof.", "sdr.", "dst.", "dll.", "ttd."],
    "vi": ["Số.", "Điều.", "Khoản.", "Mục.", "Chương."],
}

START_CLASS = {
    "es": r"[A-ZÁÉÍÓÚÑ0-9¿¡]",
    "en": r"[A-Z0-9]",
    "de": r"[A-ZÄÖÜẞ0-9]",
    "ru": r"[А-ЯЁ0-9]",
    "ms": r"[A-Z0-9]",
    "fr": r"[A-ZÀÂÇÉÈÊËÎÏÔÙÛÜŸÆŒ0-9]",
    "pt": r"[A-ZÁÀÂÃÇÉÊÍÓÔÕÚÜ0-9]",
    "it": r"[A-ZÀÈÉÌÒÓÙ0-9]",
    "nl": r"[A-ZÀ-ÖØ-Ý0-9]",
    "no": r"[A-ZÆØÅ0-9]",
    "sv": r"[A-ZÅÄÖ0-9]",
    "ar": r"[ء-ي0-9٠-٩]",
    "th": r"[ก-๙0-9๐-๙]",
    "id": r"[A-Z0-9]",
    "vi": r"[A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠ-ỹ0-9]",
}


def mask_decimal_dots(s: str) -> str:
    # 3.14, 17.07.2024
    return re.sub(r"(?<=\d)\.(?=\d)", DOT_MASK, s)


def mask_abbreviation_dots(s: str, abbr_list: list[str]) -> str:
    out = s
    for ab in sorted(abbr_list, key=len, reverse=True):
        if "." in ab:
            out = out.replace(ab, ab.replace(".", ABBR_MASK))
            out = out.replace(ab.lower(), ab.lower().replace(".", ABBR_MASK))
    return out


def unmask_all(s: str) -> str:
    return (s or "").replace(DOT_MASK, ".").replace(ABBR_MASK, ".")


def split_on_sentence_punct_general(s: str, start_char_class: str) -> list[str]:
    """
    Split after strong sentence-ending punctuation, with a "next-sentence starts with" constraint.
    Keep it conservative to avoid breaking legal enumerations too aggressively.
    """
    pattern = rf'(?<=[\.\!\?¿¡\u061F。！？])\s+(?=[\"“(\[]?{start_char_class})'
    parts = re.split(pattern, s)
    return [p.strip() for p in parts if p and p.strip()]


RE_DEHYPHEN = re.compile(r"([A-Za-zÀ-ÖØ-öø-ÿ])-\s+([A-Za-zÀ-ÖØ-öø-ÿ])")

def dehyphenate(text: str) -> str:
    """Join line-broken hyphenations: 'inter-\n national' -> 'international'."""
    return RE_DEHYPHEN.sub(r"\1\2", text or "")


def ends_with_abbrev_dot(line: str, lang: str) -> bool:
    t = (line or "").strip()
    for ab in ABBR.get(lang, []):
        if t.endswith(ab):
            return True
    return False


def merge_wrapped_lines(text: str, lang: str) -> str:
    """
    Merge PDF-extracted wrapped lines to recover paragraphs, while preserving list/section markers.
    Thai: merge aggressively (periods not reliable sentence boundaries).
    """
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    lines = [ln.strip() for ln in lines if ln.strip()]

    def is_marker(ln: str) -> bool:
        # bullets / numbering
        if re.match(r"^(\*|-|•|\u2022)\s+", ln):
            return True
        if re.match(r"^\(\s*\d+\s*\)\s+", ln):
            return True
        if re.match(r"^\d+(\.\d+)*\.\s+", ln):
            return True
        if re.match(r"^[a-zA-Z]\)\s+", ln):
            return True

        # language-specific legal markers
        if lang == "es":
            return bool(re.match(r"^(Artículo|Art\.)\b", ln)) or bool(re.match(r"^(Visto:|VISTO:|Considerando:|CONSIDERANDO:|Decreto:|DECRETO:)\b", ln)) \
                   or bool(re.match(r"^(CAP[IÍ]TULO|T[ÍI]TULO)\b", ln))
        if lang == "fr":
            return bool(re.match(r"^(Article|Section|CHAPITRE|TITRE)\b", ln, flags=re.IGNORECASE)) or bool(re.match(r"^(Vu\s*:|Consid[ée]rant\s*:|D[ée]cret\s*:)\b", ln, flags=re.IGNORECASE))
        if lang == "de":
            return bool(re.match(r"^(Artikel|Abschnitt|KAPITEL|TITEL)\b", ln, flags=re.IGNORECASE)) or bool(re.match(r"^§\s*\d+", ln))
        if lang == "en":
            return bool(re.match(r"^(Article|Section|CHAPTER|TITLE)\b", ln, flags=re.IGNORECASE))
        if lang == "ru":
            return bool(re.match(r"^(Статья|Раздел|ГЛАВА|ПРЕДИСЛОВИЕ)\b", ln))
        if lang == "ms":
            return bool(re.match(r"^(Perkara|Bahagian|BAB|PENGENALAN)\b", ln, flags=re.IGNORECASE))
        if lang == "id":
            return bool(re.match(r"^(Pasal|BAB|Bagian|Paragraf)\b", ln, flags=re.IGNORECASE))
        if lang == "it":
            return bool(re.match(r"^(Articolo|Art\.)\b", ln, flags=re.IGNORECASE)) or bool(re.match(r"^(Capo|Sezione|Titolo)\b", ln, flags=re.IGNORECASE))
        if lang == "pt":
            return bool(re.match(r"^(Artigo|Cap[ií]tulo|Se[cç][aã]o|T[ií]tulo)\b", ln, flags=re.IGNORECASE))
        if lang == "nl":
            return bool(re.match(r"^(Artikel|Hoofdstuk|Afdeling)\b", ln, flags=re.IGNORECASE))
        if lang == "no":
            return bool(re.match(r"^(Kapittel|Avsnitt|Del|§)\b", ln, flags=re.IGNORECASE))
        if lang == "sv":
            return bool(re.match(r"^(Kapitel|Avsnitt|Del|§)\b", ln, flags=re.IGNORECASE))
        if lang == "vi":
            return bool(re.match(r"^(Điều|CHƯƠNG|Chương|Mục|Khoản)\b", ln, flags=re.IGNORECASE))
        if lang == "ar":
            return bool(re.match(r"^(المادة|الباب|الفصل|القسم)\b", ln))
        if lang == "th":
            return bool(re.match(r"^(มาตรา|บท|ส่วน|หมวด|ข้อ)\b", ln))

        return False

    out = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        if i == len(lines) - 1:
            out.append(cur)
            break

        nxt = lines[i + 1]

        # Do not merge across markers (keep structure)
        if is_marker(nxt):
            out.append(cur)
            i += 1
            continue

        # Thai: merge aggressively; treat only Thai-specific end marks as boundaries
        if lang == "th":
            if re.search(r"[ฯ…]$", cur):
                out.append(cur)
                i += 1
                continue
            out.append(cur + " " + nxt)
            i += 2
            continue

        # If current line ends with strong punctuation, usually end of sentence/paragraph
        if re.search(r"[\.\!\?¿¡\u061F。！？]$", cur):
            # But avoid breaking after abbreviations like "e.g."
            if cur.endswith(".") and ends_with_abbrev_dot(cur, lang):
                out.append(cur + " " + nxt)
                i += 2
            else:
                out.append(cur)
                i += 1
            continue

        # If line ends with colon, keep as a separate line (often introduces a list)
        if cur.endswith(":"):
            out.append(cur)
            i += 1
            continue

        # Otherwise merge (handle hyphenation too)
        if cur.endswith("-"):
            out.append(cur[:-1] + nxt)
        else:
            out.append(cur + " " + nxt)
        i += 2

    return "\n".join(out)


def split_sentences(text: str, lang: str) -> list[str]:
    """
    Full sentence splitting pipeline for one page/paragraph block:
    - dehyphenate
    - mask decimals/dates (.)
    - mask abbreviations
    - split on sentence punctuation
    - unmask
    """
    t = normalize_by_lang(text or "", lang)
    if not t:
        return []

    t = dehyphenate(t)

    # For Thai: we will not rely heavily on sentence punctuation; keep line as segments after merge
    if lang == "th":
        # keep paragraphs as "sentences" here; later filtering will trim to useful ones
        parts = [p.strip() for p in re.split(r"\n+", t) if p.strip()]
        return parts

    t2 = mask_decimal_dots(t)
    t2 = mask_abbreviation_dots(t2, ABBR.get(lang, []))

    start_class = START_CLASS.get(lang, r"[A-Z0-9]")
    parts = split_on_sentence_punct_general(t2, start_class)
    parts = [unmask_all(p).strip() for p in parts if p and p.strip()]
    return parts

# sent_split_batch.py  (Part 3/3)
# -*- coding: utf-8 -*-

# ============================================================
# Quality filters + sampling + end-to-end main
# (v2: strict+relaxed fallback to avoid too-few/zero outputs)
# ============================================================

RE_CTRL = re.compile(r"[\u0000-\u001F\u007F]")
RE_MULTI_SPACE = re.compile(r"\s+")

# Very common “junk” patterns from PDFs
RE_JUNK_ONLY_PUNCT = re.compile(r"^[\W_]+$", flags=re.UNICODE)
RE_PAGE_NO_ONLY = re.compile(r"^\s*(\d{1,4}|[IVXLC]{1,8})\s*$", flags=re.IGNORECASE)
RE_MANY_DOTS = re.compile(r"\.{4,}")
RE_TOO_MANY_UNDERS = re.compile(r"_{6,}")

# Truncation / index-like patterns
RE_ELLIPSIS_END = re.compile(r"(\.\.\.|…)\s*$")
RE_BAD_END_PUNCT = re.compile(r"[:,;，؛、]\s*$")
RE_HYPHEN_END = re.compile(r"[-‐‑–—]\s*$")

# Italian TOC/index: (19) (29) (43) ...
RE_PARENS_NUM_MANY = re.compile(r"(?:\(\s*\d+\s*\)\s*){4,}")

# Arabic weird glyphs seen in broken PDF extraction
RE_AR_WEIRD_CHARS = re.compile(r"[ɺȋʈʇ؄ɢݳݨݏݰݵ]")
RE_AR_WEIRD_RUN = re.compile(r"[ɺȋʈʇ؄ɢݳݨݏݰݵ]+")

# Norwegian amendment boilerplate
RE_NO_AMEND = re.compile(r"\bEndret ved lov", flags=re.IGNORECASE)
RE_NO_IKR = re.compile(r"\bikr\.", flags=re.IGNORECASE)

# Thai labels / field-like items
RE_TH_NOTE_ONLY = re.compile(r"^\s*หมายเหตุ\s*:?\s*$")
RE_FIELD_LABEL_EN = re.compile(
    r"^\s*(Number of test report|Name|Signature|Applicant|Witness)\s*:?\s*$",
    flags=re.IGNORECASE
)


# ----------------------------
# Script ratios (gibberish check)
# ----------------------------
def ratio_arabic(text: str) -> float:
    t = text or ""
    chars = [c for c in t if not c.isspace()]
    if not chars:
        return 0.0
    ar = len(re.findall(r"[\u0600-\u06FF]", t))
    return ar / max(1, len(chars))


def ratio_thai(text: str) -> float:
    t = text or ""
    chars = [c for c in t if not c.isspace()]
    if not chars:
        return 0.0
    th = len(re.findall(r"[\u0E00-\u0E7F]", t))
    return th / max(1, len(chars))


def ratio_cyrillic(text: str) -> float:
    t = text or ""
    chars = [c for c in t if not c.isspace()]
    if not chars:
        return 0.0
    cy = len(re.findall(r"[\u0400-\u04FF]", t))
    return cy / max(1, len(chars))


def ratio_latin(text: str) -> float:
    t = text or ""
    chars = [c for c in t if not c.isspace()]
    if not chars:
        return 0.0
    la = len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]", t))
    return la / max(1, len(chars))


def clean_sentence(s: str) -> str:
    if not s:
        return ""
    s = nfkc(s)
    s = s.replace("\u00ad", "").replace("\ufeff", "")
    s = RE_CTRL.sub(" ", s)
    s = RE_MULTI_SPACE.sub(" ", s).strip()
    return s


def weird_glyph_ratio_ar(t: str) -> float:
    """
    Ratio of weird Arabic-extraction glyphs among non-space chars.
    """
    if not t:
        return 0.0
    chars = [c for c in t if not c.isspace()]
    if not chars:
        return 0.0
    bad_chars = len(RE_AR_WEIRD_CHARS.findall(t))
    return bad_chars / max(1, len(chars))


def is_sentence_junk(s: str, lang: str, strict: bool = True) -> bool:
    """
    Junk filter with strict/relaxed modes.

    strict=True: aim for high sentence quality (drops many partial/list fragments)
    strict=False: only drop obvious garbage (used as a fallback to reach N)
    """
    t = clean_sentence(s)
    if not t:
        return True

    # length gates
    if strict:
        min_len = 10 if lang in {"th", "ar"} else 16
        max_len = 600
    else:
        # relaxed: allow shorter/longer lines (still keep some sanity)
        min_len = 8 if lang in {"th", "ar"} else 12
        max_len = 900

    if len(t) < min_len:
        return True
    if len(t) > max_len:
        return True

    # generic junk
    if RE_PAGE_NO_ONLY.match(t):
        return True
    if RE_JUNK_ONLY_PUNCT.match(t):
        return True
    if RE_MANY_DOTS.search(t):
        return True
    if RE_TOO_MANY_UNDERS.search(t):
        return True

    # separators (tables)
    if t.count("|") >= (3 if strict else 4) or t.count("\t") >= (2 if strict else 3):
        return True

    # truncation signals
    if strict:
        if RE_ELLIPSIS_END.search(t):
            return True
        if RE_HYPHEN_END.search(t):
            return True
        # unbalanced brackets in strict mode (common cut-at-boundary symptom)
        if (t.count("(") != t.count(")")) or (t.count("（") != t.count("）")):
            return True

        # short label-like endings (avoid killing good long lead-in sentences)
        if RE_BAD_END_PUNCT.search(t):
            short_cut = 25 if lang in {"th", "ar"} else 35
            if len(t) < short_cut:
                return True
    else:
        # relaxed: still drop obvious ellipsis-cut lines
        if RE_ELLIPSIS_END.search(t):
            return True
        # relaxed: do NOT drop bracket imbalance; it may be legal formatting

        # relaxed: only drop very short label-like endings
        if RE_BAD_END_PUNCT.search(t):
            short_cut = 18 if lang in {"th", "ar"} else 24
            if len(t) < short_cut:
                return True

    # language-specific filters
    if lang == "it":
        # always drop TOC/index chains
        if RE_PARENS_NUM_MANY.search(t):
            return True

    if lang == "no":
        # always drop amendment boilerplate (very low value for translation eval)
        if RE_NO_AMEND.search(t) or RE_NO_IKR.search(t):
            return True

    if lang == "th":
        if RE_TH_NOTE_ONLY.match(t):
            return True
        if RE_FIELD_LABEL_EN.match(t):
            return True

    if lang == "ar":
        # strict: filter garbled sentences more aggressively
        wr = weird_glyph_ratio_ar(t)
        ar_r = ratio_arabic(t)
        if strict:
            # only kill when it's both "weird-heavy" and "Arabic-light"
            if len(t) > 40 and wr > 0.02 and ar_r < 0.25:
                return True
        else:
            # relaxed: keep more; kill only extreme garbage
            if len(t) > 60 and wr > 0.05 and ar_r < 0.18:
                return True

    # script sanity checks (light, stricter in strict mode)
    if lang == "ar":
        if ratio_arabic(t) < (0.25 if strict else 0.18) and len(t) > (40 if strict else 60):
            return True
    if lang == "th":
        if ratio_thai(t) < (0.18 if strict else 0.12) and len(t) > (40 if strict else 60):
            return True
    if lang == "ru":
        if ratio_cyrillic(t) < (0.18 if strict else 0.12) and len(t) > (50 if strict else 70):
            return True

    return False


def looks_like_heading(s: str, lang: str) -> bool:
    """
    Optional: keep headings, but avoid extremely "shouty" ones that are purely metadata.
    We mostly keep headings because legal docs have meaningful section titles.
    """
    t = clean_sentence(s)
    if not t:
        return False
    if len(t) <= 80 and uppercase_ratio_latin(t) >= 0.92 and re.search(r"[A-Za-z]", t):
        return True
    return False


def stable_hash(s: str) -> int:
    # deterministic hash (avoid Python's randomized hash)
    h = 2166136261
    for ch in (s or ""):
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def dedup_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in items:
        k = canon_line_for_template(x)
        if not k:
            k = x
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def extract_sentences_from_pdf(
    pdf_path: Path,
    lang: str,
    header_frac=0.12,
    footer_frac=0.12,
    min_template_frac=0.45,
    strict: bool = True
) -> list[dict]:
    """
    Extract candidate sentences with traceability fields.
    Returns list of dict:
      {lang, src_file, page_no, seg_id, text}
    """
    pages = prepare_pages(
        pdf_path,
        lang,
        header_frac=header_frac,
        footer_frac=footer_frac,
        min_template_frac=min_template_frac
    )
    if not pages:
        return []

    start_page = find_start_page(pages, lang)

    rows = []
    seg_idx = 0

    for pg in pages:
        if pg["page_no"] < start_page:
            continue

        page_text = pg.get("text", "") or ""
        if not page_text:
            continue
        if is_toc_like_page(page_text, lang):
            continue

        # Page-level skip for badly garbled Arabic extraction (NOW conservative)
        if lang == "ar":
            pt = clean_sentence(page_text)
            if len(pt) > 900:
                wr = weird_glyph_ratio_ar(pt)
                ar_r = ratio_arabic(pt)
                # only skip if it is very weird AND Arabic letters are scarce
                if wr > (0.02 if strict else 0.04) and ar_r < (0.20 if strict else 0.15):
                    continue

        merged = merge_wrapped_lines(page_text, lang)

        # Split by blank lines into blocks
        blocks = [b.strip() for b in re.split(r"\n{2,}", merged) if b.strip()]

        for b in blocks:
            sents = split_sentences(b, lang)
            for sent in sents:
                sent = clean_sentence(sent)
                if is_sentence_junk(sent, lang, strict=strict):
                    continue

                seg_idx += 1
                rows.append({
                    "lang": lang,
                    "src_file": pdf_path.name,
                    "page_no": pg["page_no"],
                    "seg_id": f"{pdf_path.stem}::p{pg['page_no']}::s{seg_idx:05d}",
                    "text": sent,
                })

    # Dedup within this PDF
    rows2 = []
    seen = set()
    for r in rows:
        k = canon_line_for_template(r["text"]) or r["text"]
        if k in seen:
            continue
        seen.add(k)
        rows2.append(r)

    return rows2


def sample_n(rows: list[dict], n: int, seed: int = 1234) -> list[dict]:
    """
    Deterministic-ish sampling:
    - sort by stable hash of (text + page_no)
    - take first n
    """
    if len(rows) <= n:
        return rows

    def key(r):
        return stable_hash(f"{r.get('text','')}|{r.get('page_no',0)}")

    rows_sorted = sorted(rows, key=key)
    return rows_sorted[:n]


def collect_src_pdfs(input_dir: Path) -> list[tuple[Path, str]]:
    """
    Return list of (pdf_path, lang) for files matching *_src_XX.pdf
    """
    pdfs = []
    for p in sorted(input_dir.glob("*.pdf")):
        lang = detect_lang_from_filename(p)
        if not lang:
            continue
        pdfs.append((p, lang))
    return pdfs


def _dedup_rows_by_text(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for r in rows:
        t = r.get("text", "")
        k = canon_line_for_template(t) or t
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def run_batch(
    input_dir: Path,
    output_dir: Path,
    per_lang_n: int = 200,
    header_frac=0.12,
    footer_frac=0.12,
    min_template_frac=0.45
):
    ensure_dir(output_dir)

    pdfs = collect_src_pdfs(input_dir)
    if not pdfs:
        raise RuntimeError(f"No *_src_XX.pdf found under: {input_dir}")

    # Extract candidates per language in two phases:
    # 1) strict pass
    # 2) relaxed pass (only to top-up if strict < N)
    strict_buckets: dict[str, list[dict]] = defaultdict(list)
    relaxed_buckets: dict[str, list[dict]] = defaultdict(list)

    for pdf_path, lang in pdfs:
        if lang not in SUPPORTED_LANGS:
            continue

        strict_rows = extract_sentences_from_pdf(
            pdf_path, lang,
            header_frac=header_frac, footer_frac=footer_frac, min_template_frac=min_template_frac,
            strict=True
        )
        strict_buckets[lang].extend(strict_rows)

    # Dedup strict candidates first
    for lang in list(strict_buckets.keys()):
        strict_buckets[lang] = _dedup_rows_by_text(strict_buckets[lang])

    # Top-up with relaxed if needed
    need_relaxed_langs = {lang for lang in strict_buckets.keys() if len(strict_buckets[lang]) < per_lang_n}
    # also include langs that had 0 strict candidates but exist in pdfs
    for _, lang in pdfs:
        if lang in SUPPORTED_LANGS and lang not in strict_buckets:
            strict_buckets[lang] = []
            need_relaxed_langs.add(lang)

    if need_relaxed_langs:
        for pdf_path, lang in pdfs:
            if lang not in need_relaxed_langs:
                continue
            relaxed_rows = extract_sentences_from_pdf(
                pdf_path, lang,
                header_frac=header_frac, footer_frac=footer_frac, min_template_frac=min_template_frac,
                strict=False
            )
            relaxed_buckets[lang].extend(relaxed_rows)

        # Dedup relaxed buckets
        for lang in need_relaxed_langs:
            relaxed_buckets[lang] = _dedup_rows_by_text(relaxed_buckets[lang])

    # Merge: strict first, then relaxed (only new texts)
    final_buckets: dict[str, list[dict]] = defaultdict(list)
    for lang in strict_buckets.keys():
        final = list(strict_buckets[lang])

        if lang in relaxed_buckets and len(final) < per_lang_n:
            seen = set(canon_line_for_template(r["text"]) or r["text"] for r in final)
            for r in relaxed_buckets[lang]:
                k = canon_line_for_template(r["text"]) or r["text"]
                if k in seen:
                    continue
                seen.add(k)
                final.append(r)
                if len(final) >= per_lang_n:
                    break

        final_buckets[lang] = final

    # Sample to N and write
    meta = []
    for lang in sorted(final_buckets.keys()):
        rows = final_buckets[lang]
        sampled = sample_n(rows, per_lang_n)

        out_rows = []
        for i, r in enumerate(sampled, start=1):
            out_rows.append({
                "lang": r["lang"],
                "src_file": r["src_file"],
                "page_no": r["page_no"],
                "seg_id": f"{lang}::{i:04d}",
                "text": r["text"],
            })

        out_path = output_dir / f"{lang}.jsonl"
        write_jsonl(out_path, out_rows)

        meta.append({
            "lang": lang,
            "strict_candidates": len(strict_buckets.get(lang, [])),
            "relaxed_candidates": len(relaxed_buckets.get(lang, [])) if lang in relaxed_buckets else 0,
            "final_candidates": len(rows),
            "output_n": len(out_rows),
            "out_file": str(out_path.resolve()),
        })

    write_jsonl(output_dir / "_meta.jsonl", meta)


# ============================================================
# CLI
# ============================================================

def parse_args():
    import argparse
    ap = argparse.ArgumentParser("sent_split_batch.py - extract 200 src sentences per language to jsonl")
    ap.add_argument("--input_dir", type=str, required=True, help="Directory containing *_src_XX.pdf files")
    ap.add_argument("--output_dir", type=str, default="out", help="Output directory for {lang}.jsonl")
    ap.add_argument("--n", type=int, default=200, help="Sentences per language")
    ap.add_argument("--header_frac", type=float, default=0.12, help="Top fraction treated as header zone")
    ap.add_argument("--footer_frac", type=float, default=0.12, help="Bottom fraction treated as footer zone")
    ap.add_argument("--min_template_frac", type=float, default=0.45, help="Min page fraction to consider a header/footer line as template")
    return ap.parse_args()


def main():
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    run_batch(
        input_dir=input_dir,
        output_dir=output_dir,
        per_lang_n=args.n,
        header_frac=args.header_frac,
        footer_frac=args.footer_frac,
        min_template_frac=args.min_template_frac,
    )


if __name__ == "__main__":
    main()
