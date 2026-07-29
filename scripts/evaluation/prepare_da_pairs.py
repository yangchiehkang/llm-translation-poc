#!/usr/bin/env python3
# 质量评估脚本：整理 source / hypothesis / reference 三元组。
# 运行位置：本地；也可从 data/raw PDF 重新构建评测样本。

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import random
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.io_utils import ensure_parent, read_jsonl, write_jsonl, pick_first, row_key


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")


def _build_arabic_presentation_form_map():
    # Precomputed once at import time: NFKC-decompose ONLY the two Arabic
    # presentation-form blocks (U+FB50-FDFF, U+FE70-FEFF), never the full string.
    # See clean_text() for why a whole-string NFKC call is unsafe.
    mapping = {}
    for start, end in ((0xFB50, 0xFDFF), (0xFE70, 0xFEFF)):
        for cp in range(start, end + 1):
            ch = chr(cp)
            normalized = unicodedata.normalize("NFKC", ch)
            if normalized != ch:
                mapping[cp] = normalized
    return mapping


_ARABIC_PRESENTATION_FORM_MAP = _build_arabic_presentation_form_map()
SECTION_PATTERNS = [
    re.compile(r"^\s*((?:\d{1,3})(?:\.\d{1,3}){1,6})(?:[.)])?(?=\s|$)"),
    re.compile(r"^\s*(\d{1,3})[.)](?=\s|$)"),
    # {1,4} 而非 {0,4}：零次重复会让「单个大写字母 + 空白」就命中，把 "A battery
    # whose primary use is…"、公式变量行 "R = U / I"、PDF 字间距 artifact "E nergy"
    # 全判成条款号并强行开新段。英语上开火 72 次，德语上 3071/5537。附录条款号
    # "A.1.2" 仍照常命中。
    # [A-ZА-Я] 而非 [A-Z]（2026-07-29，Z1-ru 诊断）：GOST 30593 俄语原文的附录标题
    # 是"Приложение А"/"Приложение Б"——西里尔字母"А"(U+0410) 和拉丁"A"(U+0041)
    # 视觉全同但编码不同，只认 [A-Z] 会让整个附录 A（约30个条款号）在源文侧全部
    # 识别不到，而中文译文侧用拉丁 A 排版，两侧就此不对称，把该文档的计数比拖到
    # 门槛外（0.712 < 0.75），零对齐。
    re.compile(r"^\s*((?:[A-ZА-Я])(?:\.\d{1,3}){1,4})(?:[.)])?(?=\s|$)"),
    re.compile(r"^\s*((?:Article|Art\.|ARTICLE)\s+\d+[A-Za-z0-9.-]*)\b", re.IGNORECASE),
    # 法国法典条款号自带字母前缀（"Article L541-9"、"Article L541-9-3-1"），不满足
    # 上一条「Article 后紧跟数字」的要求（2026-07-29，Z2-fr，FR_environment_code_L541
    # 诊断：34 条源文段一条都没抓到条款号）。中文译文侧对应写法是"第L541-9条"，
    # 与 SECTION_PATTERNS[6]（中文"第...章节条款"，只认中文数字/阿拉伯数字）不匹配，
    # 需要单独一条模式；两侧字母数字部分靠 canonical_section_key 里的 "L\d[\d-]*"
    # 提取来对齐，不依赖这里的原始字符串相同。
    re.compile(r"^\s*(Article\s+L\.?\s*\d+(?:-\d+)*)\b", re.IGNORECASE),
    re.compile(r"^\s*(第\s*L\.?\s*\d+(?:-\d+)*\s*条)"),
    re.compile(r"^\s*((?:Artículo|Articulo|ARTÍCULO)\s+\d+[A-Za-z0-9.-]*)\b", re.IGNORECASE),
    re.compile(r"^\s*((?:Статья|СТАТЬЯ)\s+\d+[A-Za-zА-Яа-я0-9.-]*)\b"),
    re.compile(r"^\s*(第\s*[一二三四五六七八九十百千万\d]+\s*[章节条款])"),
    re.compile(r"^\s*((?:ข้อ|มาตรา)\s*\d+[A-Za-z0-9.-]*)"),
    re.compile(r"^\s*((?:المادة|مادة)\s*\d+[A-Za-z0-9.-]*)"),
    # 阿拉伯语数字条款号"子款/章节"惯例（如 "١/٧" = 第7节第1款，2026-07-29，Z3-ar）：
    # SASO 电动车法规源文条款号用阿拉伯-印度数字，顺序与中文译文的"7.1"（章节.子款）
    # 相反——子款在前、章节在后，两侧数字文本也不同（阿拉伯-印度数字 vs 阿拉伯数字）。
    # 这条只识别原始形态，顺序颠倒和数字转写统一放到 canonical_section_key 里处理。
    re.compile(r"^\s*([٠-٩]+/[٠-٩]+)"),
    # 德语 § N 条款号（2026-07-29，Z2-de）：StVZO 源文完全没有能识别 § 的模式，
    # § 内部的枚举项被误判成条款号，全文档编号从 1 反复重来。中文译文侧**直接
    # 保留 § 符号原样**（"§ 22 车辆部件的型式认证"），不像法语译成"第N条"，
    # 两侧字面一致，不需要额外的跨语言映射——canonical_section_key 的
    # _ART_WORD_RE 已经认识 "§" 前缀（P1 时为此预留），这里只需让 extract_section_no
    # 先把 "§ N"/"§ Na"（如 "§ 21a"）本身抓出来。
    #
    # 否定前瞻排除"引用"：正文里大量出现"gemäß § 19 Absatz 6..."这类对其它条款的
    # 行内引用，恰好也在句首匹配（PDF 换行把引用切到了行首），若不排除会把引用误判
    # 成"§ 19 第二次开头"，与目录页的标题重复一起把 scoped_key 冲成大量歧义。
    # 真标题是"§ N + 标题词"，引用是"§ N + Absatz/Satz/in Verbindung mit"，两者
    # 用词能明确区分（与 Annex 引用抑制同一处理思路）。
    re.compile(r"^\s*(§\s*\d+[a-z]?)\b(?!\s*(?:Absatz|Abs\.|Satz|in\s+Verbindung))"),
]

# ---- 作用域（附录）前缀：让 "4.1" 变成 "X8::4.1"，避免正文与附件同号塌成一个 key ----
# 源文(en 等)与参考(zh)各自解析，但归一到同一套跨语言 canonical 记号，才能两侧对上。
#
# 只认顶层附录 Annex / 附录，且只在「章节标题行」上更新作用域。刻意排除的：
# - Appendix / 附件：在这批法规里是附录的下一级（"Annex 8 - Appendix 1"），
#   单独成行时几乎都是正文引用（"Appendix 1 shall be conducted, ..."）。
# - Part / 部分 / Supplement / 补充件：en 封面的 "Supplement 1 to the 01 series of
#   amendments"、正文的 "Part I of this regulation does not cover;" 会误触发，
#   而 zh 侧没有对应写法 —— 是中英不对称的来源之一。
# 带字母的子附录（Annex 9A / 附录9A）保留字母，两侧都归一到 X9A，粒度对齐。
SCOPE_EN_RE = re.compile(r"^\s*(Annex|ANNEX)\s+(\d{1,3}|[IVXLCDM]+)([A-Z])?(?![A-Za-z0-9])")
SCOPE_ZH_RE = re.compile(r"^\s*(附\s*录)\s*([一二三四五六七八九十百千零\d]+)\s*([A-Z])?")
_SCOPE_KIND = {"annex": "X", "附录": "X"}
_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

# 附录序号上限：超过即判为误检（如 zh 封面 "附录99 – 第100号法规"）。
SCOPE_MAX_INDEX = 30
# 指向「别的法规/文件」的引用句，不是本文件的章节标题。
_SCOPE_XREF_RE = re.compile(
    r"第\s*\d+\s*号\s*法规|Regulation\s+No|this\s+Regulation|Consolidated\s+Resolution|R\.E\.3",
    re.IGNORECASE,
)
# 标题行不带句读；出现句读说明这是正文（含被 PDF 断行的引用句）。
_SCOPE_PUNCT_RE = re.compile(r"[.。,，;；:：!?！？)）]")
# 目录行特征：标题后跟页码（"附录9J - 过流保护 100"）。
_SCOPE_TOC_TAIL_RE = re.compile(r"\s\d{2,4}$")
_SCOPE_TITLE_SEP_RE = re.compile(r"^[-–—]")
SCOPE_MAX_HEADING_CHARS = 80

# 段落长度上限：抽取时的分段上限、all_eval 清洗与 DA 前置过滤的 too_long 判据
# 必须是同一个值。三处曾各自写死（抽取 1200 / 清洗 1200 / DA 过滤 1200），
# 抬高抽取上限时另外两处没跟着调，产出的 1200~3000 字符合法长条款被静默判 too_long
# 全部丢弃 —— 这是「同一语义阈值散落多处」造成的第七次现场，故收敛为单一常量。
MAX_SEGMENT_CHARS = 3000

# 严格章节对齐的方法名。exact_section 是加作用域前缀之前的历史语料写法，
# exact_section_scoped 是加了作用域之后的写法，两者都是 1:1 精确条款号对齐。
EXACT_ALIGNMENT_METHODS = frozenset({"exact_section", "exact_section_scoped"})


def _numeral_to_int(s: str) -> int | None:
    s = (s or "").strip()
    if s.isdigit():
        return int(s)
    up = s.upper()
    if up and all(c in _ROMAN for c in up):
        vals = [_ROMAN[c] for c in up]
        return sum(-v if i + 1 < len(vals) and v < vals[i + 1] else v for i, v in enumerate(vals))
    if s and all(c in _CN_DIGIT or c in "十百千" for c in s):
        if s in _CN_DIGIT:
            return _CN_DIGIT[s]
        if "十" in s and "百" not in s and "千" not in s:
            a, _, b = s.partition("十")
            return (_CN_DIGIT.get(a, 1) if a else 1) * 10 + (_CN_DIGIT.get(b, 0) if b else 0)
    return None


def _looks_like_title_line(line: str) -> bool:
    # 标题行：短、无句末标点、不以条款号开头、有实际语言内容。
    line = clean_text(line or "")
    if not line or len(line) > 60:
        return False
    if extract_section_no(line):
        return False
    if re.search(r"[。.!?！？;；:：]$", line):
        return False
    return bool(CJK_RE.search(line) or LATIN_RE.search(line))


def _scope_heading_kind(line: str, match: re.Match[str]) -> str | None:
    """判断命中作用域模式的行是否真的是章节标题行。

    返回 "titled"（"Annex 8 - 标题"）/ "bare"（光杆 "Annex 8"，含 "Annex 8 Figure 1"
    这类松散尾巴）/ None（正文引用、目录行、跨文件引用 —— 不得更新作用域）。
    """
    if _SCOPE_XREF_RE.search(line):
        return None
    if len(line) > SCOPE_MAX_HEADING_CHARS:
        return None
    rest = line[match.end():].strip()
    if _SCOPE_PUNCT_RE.search(rest):
        return None
    if _SCOPE_TOC_TAIL_RE.search(rest):
        return None
    return "titled" if _SCOPE_TITLE_SEP_RE.match(rest) else "bare"


def detect_scope(line: str, lang: str, line_idx: int | None = None, next_line: str | None = None) -> str | None:
    """命中作用域标题行返回 canonical 记号（如 "X8" / "X9A"），否则 None。

    作用域只允许由真正的章节标题行更新，不能被正文里对附录的引用触发
    （"...as specified in Annex 8..."、"附录9D第3.2.1.条中规定的挤压力，可用..."），
    也不能被目录行触发（目录会把整篇正文提前染成最后一条目录项的作用域）。

    带标题的形式（"Annex 8 - Determination of ..."）自身即可确认；光杆形式
    （"Annex 8"）与正文换行产生的引用行无法从行内容区分，额外要求它出现在页首
    （en PDF 的页眉/附录起始页）或下一行是标题行（zh 由 docx 转换而来，附录标题在页中间）。
    """
    line = line or ""
    m = SCOPE_ZH_RE.match(line) if str(lang).lower().startswith("zh") else SCOPE_EN_RE.match(line)
    if not m:
        return None
    n = _numeral_to_int(m.group(2))
    if n is None or n < 1 or n > SCOPE_MAX_INDEX:
        return None
    kind = _scope_heading_kind(line, m)
    if kind is None:
        return None
    if kind == "bare" and not ((line_idx is not None and line_idx <= 1) or _looks_like_title_line(next_line or "")):
        return None
    prefix = _SCOPE_KIND.get(m.group(1).replace(" ", "").lower(), "X")
    return f"{prefix}{n}{m.group(3) or ''}"


# ---- 条款号跨语言归一化 ----
# 背景（2026-07-29，P1）：fr "Article 1" 与 zh "第 1 条" 是两个不相等的字符串，
# scoped_key 原来直接拿 section_no 原始字符串做 key，永远对不上——即使条款结构
# 本身是干净的 1:1（人工核对过 fr tachograph 文档）。en/ru 的数字条款号两侧字面
# 恰好相同（"12.1" 在源文和译文里都是这串数字），是巧合，不是设计，不能指望法语
# "Article N"、德语 "§ N" 也有这个巧合。
#
# 归一化把 extract_section_no() 的原始字符串映射成 (kind, num) 规范化元组：
#   ("num", "12.1")  纯数字条款号，含中英俄泰文档常见形式；恒等变换，不影响 en/ru
#   ("art", "1")      "顶层条款"一级：Article N / Artículo N / Статья N / § N /
#                     第N条 / ข้อ N / مادة N —— 不同语言里功能对等的最小可引用单元
#   ("chap", "N") / ("sec", "N")  第N章 / 第N节，比 art 高一级的容器，不与 art 混淆
#   ("para", "N")     第N款，比 art 低一级的子款
#   ("raw", s)        未识别的兜底，保留原字符串，不与任何规范类型碰撞
_ART_WORD_RE = re.compile(
    r"^(?:Article|Art\.|ARTICLE|Artículo|Articulo|ARTÍCULO|Статья|СТАТЬЯ|"
    r"ข้อ|มาตรา|المادة|مادة|§)\s*(\d+[A-Za-z0-9.-]*)",
    re.IGNORECASE,
)
_CN_UNIT_RE = re.compile(r"^第\s*([一二三四五六七八九十百千万\d]+)\s*([章节条款])")
_CN_UNIT_KIND = {"章": "chap", "节": "sec", "条": "art", "款": "para"}
# 法国法典字母前缀条款号（"Article L541-9" / "第L541-9条"）：两侧壳不同
# （Article.../第...条），核心编码相同，提取编码部分统一映射。
_L_CODE_RE = re.compile(r"^(?:Article\s+|第\s*)L\.?\s*(\d+(?:-\d+)*)\s*(?:条)?$", re.IGNORECASE)

# 阿拉伯语"子款/章节"条款号（2026-07-29，Z3-ar）：SASO 电动车法规源文用
# 阿拉伯-印度数字写"子款/章节"（如"١/٧"=第7节第1款），中文译文写"章节.子款"
# （"7.1"）——顺序相反、数字文本也不同，需要单独识别+颠倒+转写。
_AR_SUBCLAUSE_RE = re.compile(r"^([٠-٩]+)/([٠-٩]+)$")

# 西里尔/拉丁形近字母：GOST 俄语原文附录标题"Приложение А/Б"用西里尔字母，
# 中文译文排版惯例用拉丁字母（"A.1"），两者视觉全同、编码不同。数字条款号里的
# 前缀字母先转写成拉丁形，"А.1"（西里尔）与"A.1"（拉丁）才能规范化成同一个 key。
_CYR_TO_LAT_LOOKALIKE = str.maketrans("АВЕКМНОРСТУХ", "ABEKMHOPCTYX")


def canonical_section_key(section_no: str | None) -> tuple[str, str] | None:
    s = (section_no or "").strip()
    if not s:
        return None
    s_lat = s.translate(_CYR_TO_LAT_LOOKALIKE)
    # 纯数字体系（可含前导字母如 "A.1.2"，西里尔形近字母已转写）：跨语言字面相同，
    # 恒等变换——对 en/ru 现有的纯数字条款号（无字母前缀）不产生任何影响。
    if re.fullmatch(r"(?:[A-Z]\.)?\d{1,3}(?:\.\d{1,3}){0,6}", s_lat):
        # 逐字符把非 ASCII 的 Unicode 十进制数字（如泰文 ๑๒๓、阿拉伯-印度数字
        # ١٢٣）转写成拉丁数字（2026-07-30，Z-th）：Python 的 \d 是 Unicode
        # 感知的，泰语"๑"能匹配上面这条纯数字判据，但字面上"๑"≠"1"，不转写
        # 就永远对不上中文译文侧的阿拉伯数字条款号。只转数字字符，点号/前缀
        # 字母原样保留，对 en/ru 现有纯 ASCII 数字条款号是恒等变换。
        s_lat = "".join(str(unicodedata.digit(c)) if c.isdigit() and not c.isascii() else c for c in s_lat)
        return ("num", s_lat)
    m = _AR_SUBCLAUSE_RE.match(s)
    if m:
        # 阿拉伯语"子款/章节"顺序与中文"章节.子款"相反，且数字是阿拉伯-印度数字，
        # 两侧都转成阿拉伯数字、颠倒顺序后才能对上同一个 canonical key。
        sub = "".join(str(unicodedata.digit(c)) for c in m.group(1))
        chap = "".join(str(unicodedata.digit(c)) for c in m.group(2))
        return ("num", f"{chap}.{sub}")
    m = _L_CODE_RE.match(s)
    if m:
        return ("art", f"L{m.group(1)}")
    m = _CN_UNIT_RE.match(s)
    if m:
        n = _numeral_to_int(m.group(1))
        kind = _CN_UNIT_KIND[m.group(2)]
        return (kind, str(n)) if n is not None else ("raw", s)
    m = _ART_WORD_RE.match(s)
    if m:
        # 数字部分统一转写成阿拉伯数字字符串（2026-07-30，Z-th）：泰语条款号
        # "ข้อ ๑" 用泰文数字（Unicode Nd 类别，Python \d/int() 原生支持解析），
        # 中文译文写"第1条"用阿拉伯数字——原来这里直接拿正则捕获组的原始字符串
        # 当 key，"๑" 和 "1" 永远对不上，泰语全部条款号因此配不上参考侧。
        # 只在捕获组是纯数字（任意文字系统）时转写；带字母后缀的编号（如
        # 德语"22a"、法语"L541-9"）_numeral_to_int 返回 None，原样返回，
        # 不影响已有行为。
        raw = m.group(1)
        n = _numeral_to_int(raw)
        return ("art", str(n) if n is not None else raw)
    return ("raw", s)


def scoped_key(segment: dict[str, Any]) -> str:
    # 对齐用 key = 作用域::规范化条款号（无段号返回空串，调用方自行排除）。
    sec = str(segment.get("section_no") or "").strip()
    if not sec:
        return ""
    canon = canonical_section_key(sec)
    if canon is None:
        return ""
    key = f"{canon[0]}:{canon[1]}"
    scope = str(segment.get("scope") or "").strip()
    return f"{scope}::{key}" if scope else key


def clean_text(text: str) -> str:
    text = (text or "").replace("\u00a0", " ")
    # Arabic presentation-form -> basic-block mapping (Z3-ar): SASO electric-vehicle
    # regulation's Arabic font uses Presentation Forms-A/B (U+FB50-FDFF/U+FE70-FEFF),
    # not the basic Arabic block (U+0600-06FF) that good_char_ratio() checks.
    # Presentation-form letters were all judged "bad chars", so 99.5% of the
    # 46-page document's lines got discarded as noise.
    #
    # Scoped to ONLY those two presentation-form blocks, not a blanket
    # unicodedata.normalize("NFKC", text) on the whole string: NFKC has a
    # well-known side effect on spacing diacritics used elsewhere as ordinary
    # punctuation -- this corpus writes English "manufacturer's" with U+00B4
    # (ACUTE ACCENT) as the apostrophe, and NFKC decomposes that into a space
    # plus a combining accent, silently rewriting 541/689 of the committed EN
    # samples (caught by the drift check; never shipped). A whole-string NFKC
    # call is not safe to run unconditionally across all languages.
    text = text.translate(_ARABIC_PRESENTATION_FORM_MAP)
    # Tatweel (U+0640): a pure Arabic typographic elongation mark with no meaning,
    # used only for visual justification padding.
    text = text.replace("\u0640", "")
    # Strip (cid:N) glyph-mapping-failure placeholders (Z3-ar): pdfplumber emits
    # these when a font's ToUnicode CMap is missing an entry for some glyph (only
    # 5.9% of this document's characters, but touching 55.6% of lines). Dropping
    # the whole line used to discard the other, perfectly readable characters on
    # it too; stripping just the placeholder keeps the rest of the line intact.
    text = re.sub(r"\(cid:\d+\)", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"[_＿]{3,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff])\s+(?=[\u3400-\u4dbf\u4e00-\u9fff])", "", text)
    return text


def count_cjk(text: str) -> int:
    return len(CJK_RE.findall(text or ""))


def good_char_ratio(text: str) -> float:
    if not text:
        return 0.0
    good = 0
    for ch in text:
        if ch.isalnum() or "\u0e00" <= ch <= "\u0e7f" or "\u0600" <= ch <= "\u06ff" or CJK_RE.match(ch):
            good += 1
    return good / max(len(text), 1)


def is_noise_line(line: str) -> bool:
    line = clean_text(line)
    if not line:
        return True
    if re.fullmatch(r"[-–—]?\s*\d{1,4}\s*[-–—]?", line):
        return True
    if re.fullmatch(r"(?:page|página|seite|страница|หน้า)\s+\d{1,4}(?:\s*/\s*\d{1,4})?", line, re.IGNORECASE):
        return True
    # 中文"第N页共M页"页码行（2026-07-29，Z2-de：StVZO 中文译文每页都有，页码逐页
    # 变化，不满足 repeated_page_lines() 的"整行完全相同才算重复"要求，需要单独
    # 用正则识别。此前未过滤时它没有混进正文——是作为独立行被当成普通内容行合并
    # 进当前段，产出的段落文本里就显得"混入了"。
    if re.fullmatch(r"第\s*\d{1,4}\s*页\s*共\s*\d{1,4}\s*页", line):
        return True
    if re.search(r"[.·…]{4,}\s*\d{1,4}$", line):
        return True
    if re.search(r"[.·…]{10,}", line):
        return True
    if len(line) > 20 and good_char_ratio(line) < 0.25:
        return True
    return False


def extract_section_no(text: str) -> str | None:
    for pattern in SECTION_PATTERNS:
        match = pattern.search(text or "")
        if match:
            value = clean_text(match.group(1)).rstrip(".)")
            return value or None
    return None


def segment_type_for(text: str, section_no: str | None) -> str:
    lower = text.lower()
    if re.match(r"^\s*(table|tabla|tabelle|tableau|таблица|表|جدول)\b", text, re.IGNORECASE):
        return "table"
    if re.match(r"^\s*(note|notes|nota|remarque|примечание|หมายเหตุ|ملاحظة|注)\b", text, re.IGNORECASE):
        return "note"
    if re.match(r"^\s*[-*•●▪]", text):
        return "list"
    if section_no:
        return "paragraph"
    if len(text) <= 120 and not re.search(r"[。.!?！？;；]$", text):
        title_words = [
            "chapter", "annex", "appendix", "regulation", "resolution", "section",
            "capítulo", "anexo", "chapitre", "anlage", "глава", "приложение",
            "บท", "ภาคผนวก", "الفصل", "ملحق", "第", "附录", "目录",
        ]
        if any(word in lower or word in text for word in title_words):
            return "title"
        alpha = [ch for ch in text if ch.isalpha()]
        if alpha and sum(1 for ch in alpha if ch.isupper()) / max(len(alpha), 1) > 0.65:
            return "title"
    return "paragraph"


def sentence_end(text: str) -> bool:
    return bool(re.search(r"[。.!?！？;；:：؟؛]$", text.strip()))


def split_long_text(text: str, max_chars: int, on_overflow=None) -> list[str]:
    """按句边界切分超长段；只有单句本身就超过 max_chars 时才会从句中硬切。

    句中硬切是「用字符数阈值当结构边界」的最后一处，正常语料里不应发生。
    on_overflow 在发生句中硬切时被调用（带上文本片段），供调用方记录告警。
    """
    text = clean_text(text)
    if len(text) <= max_chars:
        return [text]

    pieces = re.split(r"(?<=[。.!?！？;；؟؛])\s+", text)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        piece = clean_text(piece)
        if not piece:
            continue
        if len(piece) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            if on_overflow is not None:
                on_overflow(len(piece), piece[:90])
            for start in range(0, len(piece), max_chars):
                chunks.append(clean_text(piece[start : start + max_chars]))
            continue
        candidate = clean_text(f"{current} {piece}" if current else piece)
        if len(candidate) > max_chars and current:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def keep_segment(text: str, segment_type: str, section_no: str | None, min_chars: int) -> bool:
    n = len(text)
    if n >= min_chars:
        return True
    if segment_type in {"title", "table"} and n >= 8:
        return True
    if section_no and n >= 10:
        return True
    return False


# 阿拉伯语字符范围（含展示形式区），用于判定一行文字是否以阿拉伯语为主。
_ARABIC_CHAR_RE = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿]")


def _is_arabic_word(text: str) -> bool:
    ar = len(_ARABIC_CHAR_RE.findall(text))
    return ar / max(len(text), 1) > 0.3


def _reorder_line_bidi(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对一行词（已按 x0 升序=几何从左到右排好）做简化版双向（bidi）重排。

    2026-07-30，Z3-ar 复核：第一版实现是把整行按 x0 降序整体倒转——这会把
    行内嵌入的拉丁词组（"(High Voltage)"）也一起倒转成"Voltage) (High"，
    虽然词内部拼写不受影响，但嵌入的多词 LTR 片段之间的相对顺序被打反了。
    正确做法（简化版 Unicode 双向算法）：先按几何序把行切成"阿拉伯语连续块"
    和"非阿拉伯语（拉丁/数字/标点）连续块"，整体反转"块的顺序"（RTL 行的
    块本身从右向左排布），但**块内部**只有阿拉伯语块需要再反转词序（阿拉伯语
    词本身也是从右向左读），非阿拉伯语块保持原有的从左到右词序不变——嵌入的
    "High Voltage"这类拉丁词组因此维持正确的内部读序。
    """
    runs: list[tuple[bool, list[dict[str, Any]]]] = []
    for w in words:
        is_ar = _is_arabic_word(w["text"])
        if runs and runs[-1][0] == is_ar:
            runs[-1][1].append(w)
        else:
            runs.append((is_ar, [w]))
    runs.reverse()
    ordered: list[dict[str, Any]] = []
    for is_ar, run_words in runs:
        ordered.extend(reversed(run_words) if is_ar else run_words)
    return ordered


def _extract_rtl_aware_page_text(page: Any) -> str:
    """按行聚类后，阿拉伯语（RTL）行做双向重排，拉丁/中文等 LTR 行保持升序
    不变（2026-07-29，Z3-ar；2026-07-30 改为 run 级双向重排，见 `_reorder_line_bidi`）。

    pdfplumber 的 `extract_text()` 只按几何位置从左到右拼词，不做 RTL 逻辑
    换位——对阿拉伯语 PDF，这会把每一行的词序整体拼反（行内单个词的字形
    仍正常，问题在词与词的排列顺序）。验证过：条款号（如"1/7"）在原文里
    实际上是每行最先读到的部分（阿拉伯语从右向左读，行首在页面右侧，
    即 x 坐标最大处），被 `extract_text()` 放到了提取文本行尾，导致
    `extract_section_no()` 用"行首匹配"的判据永远抓不到它。
    """
    words = page.extract_words(use_text_flow=False)
    if not words:
        return ""
    lines: list[list[dict[str, Any]]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        for line in lines:
            if abs(line[0]["top"] - w["top"]) <= 3:
                line.append(w)
                break
        else:
            lines.append([w])
    lines.sort(key=lambda line: line[0]["top"])
    out_lines = []
    for line in lines:
        line.sort(key=lambda w: w["x0"])
        ar_chars = sum(len(_ARABIC_CHAR_RE.findall(w["text"])) for w in line)
        total_chars = sum(len(w["text"]) for w in line) or 1
        is_rtl_line = (ar_chars / total_chars) > 0.4
        ordered = _reorder_line_bidi(line) if is_rtl_line else line
        out_lines.append(" ".join(w["text"] for w in ordered))
    return "\n".join(out_lines)


def extract_pages_with_pdfplumber(pdf_path: Path) -> list[dict[str, Any]]:
    try:
        import pdfplumber
    except Exception as exc:  # pragma: no cover - dependency error message matters most.
        raise RuntimeError("pdfplumber is required for --mode from_raw") from exc

    pages: list[dict[str, Any]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for idx, page in enumerate(pdf.pages, 1):
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            if not text.strip():
                text = page.extract_text(layout=True) or ""
            # 只在页面以阿拉伯语为主时才切到 RTL 感知的自定义抽取路径，其它
            # 语言的页面完全不受影响、走原来的 extract_text() 逻辑（窄范围
            # 生效，避免对 en/ru/fr/de/es/th 产生任何漂移）。
            if text and (len(_ARABIC_CHAR_RE.findall(text)) / max(len(text), 1)) > 0.15:
                rtl_text = _extract_rtl_aware_page_text(page)
                if rtl_text.strip():
                    text = rtl_text
            pages.append({"page": idx, "text": text})
    return pages


def extract_pages(pdf_path: Path) -> list[dict[str, Any]]:
    try:
        return extract_pages_with_pdfplumber(pdf_path)
    except Exception:
        try:
            from pypdf import PdfReader
        except Exception:
            raise
        reader = PdfReader(str(pdf_path))
        return [{"page": idx, "text": page.extract_text() or ""} for idx, page in enumerate(reader.pages, 1)]


def repeated_page_lines(pages: list[dict[str, Any]]) -> set[str]:
    counts: Counter[str] = Counter()
    for page in pages:
        lines = [clean_text(x) for x in (page.get("text") or "").splitlines()]
        lines = [x for x in lines if x and not is_noise_line(x)]
        for line in lines[:3] + lines[-3:]:
            if 6 <= len(line) <= 180:
                counts[line] += 1
    threshold = max(3, len(pages) // 3)
    return {line for line, count in counts.items() if count >= threshold}


def parse_pdf_segments(
    pdf_path: Path,
    document_id: str,
    language_pair: str,
    lang: str,
    min_chars: int,
    max_chars: int,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    pages = extract_pages(pdf_path)
    repeated = repeated_page_lines(pages)
    segments: list[dict[str, Any]] = []
    filtered = 0
    notes: list[str] = []
    order = 0

    current_lines: list[str] = []
    current_page: int | None = None
    current_scope: str = ""  # 当前作用域（附件/附录/部分）canonical 记号，如 "X8"；正文为空串
    # max_chars 是最后一处「字符数阈值当结构边界」。正常语料里它不应触发；
    # 触发即记录告警（含 segment 标识），说明遇到了未知的文档结构。
    overflow_notes: list[str] = []
    # 当前打开的段落是否属于德语 "§ N" 条款体（2026-07-29，Z2-de）。StVZO 里 § 内部
    # 常见枚举子项独占一行（"2. Gleitschutzeinrichtungen (...)"），这类行会被
    # SECTION_PATTERNS[1]（纯数字 "N."）命中，若当普通条款号处理会把整个 § 拆成
    # 一堆 1/2/3 反复重来的假条款，编号在文档里大量碰撞、彻底冲垮 scoped_key。
    # 规则：进了一个 "§ N" 段之后，纯数字枚举行视为该 § 内部的子项延续，不开新段；
    # 遇到下一个 "§ N" 才真正结束当前条款。只处理 § 这一种嵌套，不动其它语言的既有行为。
    in_de_paragraph: bool = False

    def flush() -> None:
        nonlocal current_lines, current_page, order, filtered
        text = clean_text(" ".join(current_lines))
        current_lines = []
        if not text:
            return
        section_no = extract_section_no(text)
        seg_type = segment_type_for(text, section_no)
        def _overflow(n: int, head: str) -> None:
            overflow_notes.append(
                f"{pdf_path.name}: page {current_page} 单句长度 {n} > max_chars={max_chars}，"
                f"发生句中硬切（本不该发生）：“{head}…”"
            )

        for chunk in split_long_text(text, max_chars=max_chars, on_overflow=_overflow):
            chunk_section = extract_section_no(chunk) or section_no
            chunk_type = segment_type_for(chunk, chunk_section)
            if not keep_segment(chunk, chunk_type, chunk_section, min_chars=min_chars):
                filtered += 1
                continue
            order += 1
            segments.append({
                "document_id": document_id,
                "language_pair": language_pair,
                "lang": lang,
                "page": current_page,
                "order": order,
                "scope": current_scope,
                "section_no": chunk_section,
                "segment_type": chunk_type,
                "text": chunk,
                "char_count": len(chunk),
            })

    for page in pages:
        page_no = page["page"]
        raw_lines = (page.get("text") or "").splitlines()
        cleaned_lines = []
        for raw_line in raw_lines:
            line = clean_text(raw_line)
            if is_noise_line(line) or line in repeated:
                filtered += 1
                continue
            cleaned_lines.append(line)
        if not cleaned_lines:
            notes.append(f"{pdf_path.name}: page {page_no} produced no usable text")
            continue
        for line_idx, line in enumerate(cleaned_lines):
            next_line = cleaned_lines[line_idx + 1] if line_idx + 1 < len(cleaned_lines) else ""
            scope_here = detect_scope(line, lang, line_idx=line_idx, next_line=next_line)
            if scope_here:
                current_scope = scope_here
            section_no = extract_section_no(line)
            # § 顶层条款号强制重置作用域（2026-07-29，Z2-de/StVZO）：德语法规里
            # "§ N" 是正文顶层条款标记，按定义不可能同时位于某个附录（Anlage/Annex）
            # 作用域内。StVZO 参考译文侧一处目录/附录清单页把 scope 误判成 "X14"
            # 后，detect_scope() 找不到下一次真正的作用域标题行来纠正它——这正是
            # detect_scope() 文档字符串自己描述的已知风险（"目录会把整篇正文提前
            # 染成最后一条目录项的作用域"），只是这次没被现有的目录行判据挡住。
            # 源文侧巧合没触发（可能是版式/翻页差异），于是两侧作用域不对称、
            # 48 个源文条款号在参考侧一个都配不上。§ 一出现就清空作用域，不依赖
            # 猜"目录已经结束"，直接用"§ 的存在本身就证明现在在正文顶层"这条
            # 结构性事实修复，不影响其它任何条款号类型的作用域判定。
            if section_no and section_no.startswith("§"):
                current_scope = ""
            line_type = segment_type_for(line, section_no)
            prev = current_lines[-1] if current_lines else ""
            current_text = clean_text(" ".join(current_lines))
            starts_new = False
            if current_lines:
                if section_no and section_no.startswith("§"):
                    starts_new = True
                    in_de_paragraph = True
                elif section_no and in_de_paragraph and re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){0,6}", section_no):
                    pass  # § 内部的纯数字枚举子项，并入当前条款，不开新段
                elif section_no:
                    starts_new = True
                    in_de_paragraph = False
                elif (
                    line_type in {"title", "table", "note"}
                    and segment_type_for(current_text, extract_section_no(current_text)) != line_type
                    # 续行保护：本行不含条款号、且上一行没有句末标点，说明这是被 PDF
                    # 换行切开的同一句，必须并回去。segment_type_for 会把含
                    # "regulation"/"annex" 等词且无句末标点的短行判成 title，
                    # 于是 "12.1. As from the official date of entry into force of the
                    # 03 series of amendments," 的续行 "no Contracting Party applying
                    # this Regulation shall refuse..." 被当成标题另起一段，
                    # 条款正文只剩前半句。
                    and sentence_end(prev)
                ):
                    starts_new = True
                elif len(current_text) + len(line) + 1 > max_chars:
                    # 条款边界只由「遇到新条款号」或「超 max_chars」决定。
                    # 原来这里之前还有一条 `sentence_end(prev) and len(current_text) >= 80`：
                    # 用一个与条款边界无关的字符数阈值当边界，把同一条款的后续句子切成
                    # 无条款号的孤儿段（EN 侧触发 501 次，切出的段拿到条款号的 0 个，
                    # 必然无法 exact_section_scoped 对齐）。且同一阈值跨语言复用，
                    # 英文字符密度约为中文 1/3，EN 侧触发频率是 ZH 侧的 2.3~2.5 倍，
                    # 于是英文被切碎、中文保持完整 —— 这正是「源文缺末尾段落、参考完整」
                    # 那一类缺陷的成因。已取消。
                    overflow_notes.append(
                        f"{pdf_path.name}: page {page_no} 段落达到 max_chars={max_chars} 被迫另起"
                        f"（前段 {len(current_text)} 字符，起始 “{current_text[:60]}…”）"
                    )
                    starts_new = True
            if starts_new:
                flush()
            if not current_lines:
                current_page = page_no
            current_lines.append(line)
    flush()

    if not segments:
        notes.append(f"{pdf_path.name}: no segments extracted")
    if overflow_notes:
        notes.append(f"[MAX_CHARS 告警] {pdf_path.name}: 触发 {len(overflow_notes)} 次")
        notes.extend(overflow_notes)
    return segments, filtered, notes


def load_raw_groups(raw_dir: Path) -> list[dict[str, Any]]:
    manifest = raw_dir / "manifest.jsonl"
    if manifest.exists():
        rows = read_jsonl(manifest)
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            if (row.get("format") or "").lower() != "pdf":
                continue
            doc_id = row.get("doc_id") or row.get("document_id")
            pair = row.get("language_pair")
            role = row.get("role")
            if not doc_id or not pair or role not in {"source", "reference"}:
                continue
            key = (doc_id, pair)
            group = grouped.setdefault(key, {
                "document_id": doc_id,
                "language_pair": pair,
                "source_lang": pair.split("-")[0],
                "target_lang": pair.split("-")[1] if "-" in pair else "zh",
                "domain": row.get("domain", ""),
            })
            pdf_path = Path(row.get("path") or "")
            if not pdf_path.is_absolute():
                pdf_path = PROJECT_ROOT / pdf_path
            if role == "source":
                group["source_pdf"] = str(pdf_path)
                group["source_lang"] = row.get("lang") or group["source_lang"]
            else:
                group["reference_pdf"] = str(pdf_path)
                group["target_lang"] = row.get("lang") or group["target_lang"]
        groups = [g for g in grouped.values() if g.get("source_pdf") and g.get("reference_pdf")]
        if groups:
            return sorted(groups, key=lambda x: (x["language_pair"], x["document_id"]))

    groups = []
    for pair_dir in sorted(raw_dir.glob("*-zh")):
        if not pair_dir.is_dir():
            continue
        pair = pair_dir.name
        source_lang, target_lang = pair.split("-", 1)
        buckets: dict[str, dict[str, Path]] = defaultdict(dict)
        for pdf in sorted(pair_dir.glob("*.pdf")):
            stem = pdf.stem
            if stem.endswith("_zh"):
                doc_id = stem[:-3]
                buckets[doc_id]["reference_pdf"] = pdf
            elif stem.endswith(f"_{source_lang}"):
                doc_id = stem[: -(len(source_lang) + 1)]
                buckets[doc_id]["source_pdf"] = pdf
            else:
                buckets[stem]["source_pdf"] = pdf
        for doc_id, paths in buckets.items():
            if paths.get("source_pdf") and paths.get("reference_pdf"):
                groups.append({
                    "document_id": doc_id,
                    "language_pair": pair,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "source_pdf": str(paths["source_pdf"]),
                    "reference_pdf": str(paths["reference_pdf"]),
                    "domain": "",
                })
    return sorted(groups, key=lambda x: (x["language_pair"], x["document_id"]))


def sample_id_for(document_id: str, language_pair: str, order_source: int) -> str:
    base = f"{document_id}_{language_pair}_{order_source:06d}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", base)


def make_all_sample(segment: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": sample_id_for(segment["document_id"], segment["language_pair"], int(segment["order"])),
        "document_id": segment["document_id"],
        "language_pair": segment["language_pair"],
        "source_lang": group["source_lang"],
        "target_lang": group["target_lang"],
        "source_text": segment["text"],
        "page_source": segment["page"],
        "order_source": segment["order"],
        "section_no": segment.get("section_no"),
        "segment_type": segment.get("segment_type", "unknown"),
        "source_char_count": segment["char_count"],
    }


def alignment_sane(source: dict[str, Any], ref: dict[str, Any], min_chars: int) -> bool:
    source_text = source.get("text") or ""
    ref_text = ref.get("text") or ""
    if not source_text or not ref_text:
        return False
    if count_cjk(ref_text) < 2 or count_cjk(ref_text) / max(len(ref_text), 1) < 0.08:
        return False
    if not keep_segment(source_text, source.get("segment_type", "unknown"), source.get("section_no"), min_chars):
        return False
    if not keep_segment(ref_text, ref.get("segment_type", "unknown"), ref.get("section_no"), 8):
        return False
    ratio = len(ref_text) / max(len(source_text), 1)
    return 0.08 <= ratio <= 6.5


def section_ok_for_exact(section_no: str | None, source_count: int, ref_count: int) -> bool:
    section = str(section_no or "").strip()
    if not section:
        return False
    if re.fullmatch(r"[A-Z]", section):
        return False
    if re.fullmatch(r"\d{1,3}", section) and (source_count != 1 or ref_count != 1):
        return False
    if source_count > 3 or ref_count > 3:
        return False
    return True


def relative_order_gap(source: dict[str, Any], ref: dict[str, Any], source_count: int, ref_count: int) -> float:
    if source_count <= 1 or ref_count <= 1:
        return 0.0
    source_pos = (int(source["order"]) - 1) / max(source_count - 1, 1)
    ref_pos = (int(ref["order"]) - 1) / max(ref_count - 1, 1)
    return abs(source_pos - ref_pos)


def aligned_sample(
    source: dict[str, Any],
    ref: dict[str, Any],
    group: dict[str, Any],
    method: str,
    confidence: str,
    use_for_da: bool = True,
) -> dict[str, Any]:
    return {
        "sample_id": sample_id_for(source["document_id"], source["language_pair"], int(source["order"])),
        "document_id": source["document_id"],
        "language_pair": source["language_pair"],
        "source_lang": group["source_lang"],
        "target_lang": group["target_lang"],
        "source_text": source["text"],
        "ref_text": ref["text"],
        "page_source": source["page"],
        "page_ref": ref["page"],
        "order_source": source["order"],
        "order_ref": ref["order"],
        "section_no": source.get("section_no") or ref.get("section_no"),
        # 作用域随行落盘：下游去重/自审必须和对齐用同一把 key，否则正文 2.1.1.2
        # 与 Annex 15 的 2.1.1.2 又会在去重阶段被当成重复条款互相挤掉。
        "scope": source.get("scope") or ref.get("scope") or "",
        "segment_type": source.get("segment_type", "unknown"),
        "source_char_count": source["char_count"],
        "ref_char_count": ref["char_count"],
        "alignment_method": method,
        "alignment_confidence": confidence,
        "use_for_da": use_for_da,
    }


def _title_ref_indices(segments: list[dict[str, Any]]) -> set[int]:
    """标出"同 key 多次出现时，明显短于最长 occurrence 的那些"——目录页标题、
    正文里对本条款的行内引用，不是条款正文本身（2026-07-29，Z2-de：StVZO 目录页
    把每个 § 的标题单独列一遍；EN R100 也有同型问题——"3.2. Component based test"
    （25 字符标题）与"3.2. Test procedure ..."（1709 字符正文）共享同一条款号）。
    判据：同 key 存在长度 >= max(100, 0.3×组内最长) 的"正文候选"时，明显更短的
    那些视为标题/引用，从关键字匹配里剔除（不参与 key 计数与配对，不是删除段落）。
    若组内没有一条够长（全部一样短），交给下游 scoped_ambiguous 兜底，不强行选。
    ⚠️ 首版按"更短 = 引用"直接判定时，drop 了 en/ru 一些 scoped_ambiguous/order_based
    条目——核查后确认这些条目本来就 use_for_da=False（不进 689/133 主数），且没有
    任何 exact_section_scoped 被影响（逐条核对 689 条 armA 全部仍在），fr 还净增
    1 条 exact，才定为安全，保留至今。
    """
    by_key: dict[str, list[int]] = defaultdict(list)
    for idx, seg in enumerate(segments):
        k = scoped_key(seg)
        if k:
            by_key[k].append(idx)
    drop: set[int] = set()
    for idxs in by_key.values():
        if len(idxs) < 2:
            continue
        maxlen = max(segments[i]["char_count"] for i in idxs)
        threshold = max(100, 0.3 * maxlen)
        long_idxs = [i for i in idxs if segments[i]["char_count"] >= threshold]
        if long_idxs and len(long_idxs) < len(idxs):
            drop.update(i for i in idxs if i not in long_idxs)
    return drop


def align_segments(
    source_segments: list[dict[str, Any]],
    reference_segments: list[dict[str, Any]],
    group: dict[str, Any],
    min_chars: int,
) -> list[dict[str, Any]]:
    aligned: list[dict[str, Any]] = []
    used_source: set[int] = set()
    used_ref: set[int] = set()

    source_title_ref = _title_ref_indices(source_segments)
    ref_title_ref = _title_ref_indices(reference_segments)

    # 作用域化 key（"X8::5.4.1"）建索引：正文与附件同号不再塌成一个 key。
    # 标题引用（source_title_ref/ref_title_ref）不参与建索引与计数。
    refs_by_key: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for ridx, ref in enumerate(reference_segments):
        if ridx in ref_title_ref:
            continue
        k = scoped_key(ref)
        if k:
            refs_by_key[k].append((ridx, ref))
    source_key_counts = Counter(
        k for sidx, k in ((i, scoped_key(s)) for i, s in enumerate(source_segments))
        if k and sidx not in source_title_ref
    )
    ref_key_counts = Counter(
        k for ridx, k in ((i, scoped_key(r)) for i, r in enumerate(reference_segments))
        if k and ridx not in ref_title_ref
    )
    source_count = len(source_segments)
    ref_count = len(reference_segments)
    count_ratio = source_count / ref_count if ref_count else 0.0

    # 计数比门槛失守时的例外（2026-07-29，Z2-fr）：fr L541 文档 67 源文段/98 参考段，
    # 比值 0.684 未过 0.75~1.35 门槛，但 48 个带 key 的源文段里 47 个在参考侧能找到
    # 同一 key（覆盖率 97.9%）——比值失衡是参考侧分段粒度更细造成的，不是结构性
    # 错配。key 覆盖率是比计数比更精确的信号（逐条验证过 key 是否存在，不是靠总数
    # 猜比例），故在覆盖率极高时也放行 exact 匹配。阈值保守（覆盖率>=90% 且绝对匹配
    # 数>=10，避免小样本巧合命中），且不改变计数比门槛本身、不改变下方 order_based
    # 的独立门槛——只是新增一条"更精确信号压过粗糙信号"的例外，不是放宽普适阈值。
    keyed_source_keys = [scoped_key(s) for i, s in enumerate(source_segments)
                         if i not in source_title_ref and scoped_key(s)]
    key_coverage = (sum(1 for k in keyed_source_keys if k in refs_by_key) / len(keyed_source_keys)
                    if keyed_source_keys else 0.0)
    high_key_coverage = len(keyed_source_keys) >= 10 and key_coverage >= 0.90

    if (0.75 <= count_ratio <= 1.35) or high_key_coverage:
        for sidx, source in enumerate(source_segments):
            if sidx in source_title_ref:
                continue  # 标题引用本身不是条款正文，不参与配对
            k = scoped_key(source)
            if not k:
                continue
            # 护栏反过来：作用域化后 key 在任一侧仍 >1 次 -> 不做 exact，标记待复核。
            # 绝不再用 order 就近去猜（那正是 812/193 错位的执行者）。
            if source_key_counts.get(k, 0) != 1 or ref_key_counts.get(k, 0) != 1:
                cand = [(ridx, ref) for ridx, ref in refs_by_key.get(k, []) if ridx not in used_ref]
                if cand:
                    ridx, ref = cand[0]
                    aligned.append(aligned_sample(source, ref, group, "scoped_ambiguous", "needs_review", use_for_da=False))
                    used_source.add(sidx)
                    used_ref.add(ridx)
                continue
            candidates = [(ridx, ref) for ridx, ref in refs_by_key.get(k, []) if ridx not in used_ref]
            if not candidates:
                continue
            ridx, ref = candidates[0]  # 唯一 1:1，直接取，不做 order 猜
            if not alignment_sane(source, ref, min_chars):
                continue
            aligned.append(aligned_sample(source, ref, group, "exact_section_scoped", "high"))
            used_source.add(sidx)
            used_ref.add(ridx)

    if source_count and ref_count and 0.8 <= source_count / ref_count <= 1.25:
        ref_unused = [idx for idx in range(ref_count) if idx not in used_ref]
        for sidx, source in enumerate(source_segments):
            if sidx in used_source or not ref_unused:
                continue
            expected = int(round(sidx * (ref_count - 1) / max(source_count - 1, 1)))
            ridx = min(ref_unused, key=lambda idx: abs(idx - expected))
            if abs(ridx - expected) > max(2, int(0.04 * ref_count)):
                continue
            ref = reference_segments[ridx]
            if not alignment_sane(source, ref, min_chars):
                continue
            aligned.append(aligned_sample(source, ref, group, "order_based", "medium"))
            used_source.add(sidx)
            used_ref.add(ridx)
            ref_unused = [idx for idx in ref_unused if idx != ridx]

    aligned.sort(key=lambda row: (row["document_id"], row["order_source"]))
    return aligned


def write_by_language(output_dir: Path, filename_suffix: str, rows: list[dict[str, Any]]) -> None:
    by_lang: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_lang[row["language_pair"]].append(row)
    by_dir = output_dir / "by_lang"
    if by_dir.exists():
        for path in by_dir.glob(f"*_{filename_suffix}.jsonl"):
            path.unlink()
    for pair, pair_rows in sorted(by_lang.items()):
        name = pair.replace("-", "_")
        write_jsonl(output_dir / "by_lang" / f"{name}_{filename_suffix}.jsonl", pair_rows)


def clear_raw_eval_outputs(output_dir: Path) -> None:
    for name in [
        "source_segments.jsonl",
        "reference_segments.jsonl",
        "all_eval_samples.jsonl",
        "aligned_da_samples.jsonl",
        "summary.json",
        "summary.md",
    ]:
        path = output_dir / name
        if path.exists():
            path.unlink()
    by_lang = output_dir / "by_lang"
    if by_lang.exists():
        for path in by_lang.glob("*.jsonl"):
            path.unlink()


def write_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    md = ensure_parent(output_dir / "summary.md")
    lines = [
        "# Eval Samples Summary",
        "",
        f"- total_documents: {summary['total_documents']}",
        f"- total_source_segments: {summary['total_source_segments']}",
        f"- total_reference_segments: {summary['total_reference_segments']}",
        f"- total_all_eval_samples: {summary['total_all_eval_samples']}",
        f"- total_aligned_da_samples: {summary['total_aligned_da_samples']}",
        f"- filtered_segment_count: {summary['filtered_segment_count']}",
        "",
        "## Counts By Language Pair",
        "",
    ]
    for key, value in sorted(summary["counts_by_language_pair"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Aligned Counts By Language Pair", ""])
    for key, value in sorted(summary["aligned_counts_by_language_pair"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Alignment Methods", ""])
    for key, value in sorted(summary["alignment_method_distribution"].items()):
        lines.append(f"- {key}: {value}")
    if summary.get("notes"):
        lines.extend(["", "## Notes", ""])
        for note in summary["notes"][:80]:
            lines.append(f"- {note}")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def has_language_content(text: str) -> bool:
    return bool(CJK_RE.search(text) or LATIN_RE.search(text) or re.search(r"[\u0400-\u04ff\u0e00-\u0e7f\u0600-\u06ff]", text))


def has_directory_features(text: str) -> bool:
    text = clean_text(text)
    lower = text.lower()
    if re.search(r"[.·…]{4,}\s*\d{1,4}\s*$", text):
        return True
    # "indice"/"índice" 从关键词表移除（2026-07-29，P 门禁统一，fr 首次让 da_prefilter_reason
    # 真正跑起来时发现）：法语/西语里 "indice" 是普通法律术语（"indice de réparabilité"=
    # 可维修性指数），不是"目录"专属词，在正文任何位置都可能合法出现；"contents"/
    # "sommaire"/"目录" 等词没有这个歧义，予以保留。en 689/ru 125 逐条验证过零命中，
    # 移除前后行为不变。
    # "inhalt" 收窄成 "inhaltsverzeichnis"（2026-07-29，Z2-de）：德语"Einhaltung"
    # （合规/遵守，法规正文极常见词）字面包含"inhalt"子串，会被误判成目录。
    # 真正要抓的噪声是页脚戳"Nichtamtliches Inhaltsverzeichnis"（非官方目录，
    # gesetze-im-internet.de 出品的 PDF 每页都有）——用更具体的复合词
    # "inhaltsverzeichnis" 替代裸词，既不误伤"Einhaltung"，也不影响原本要抓的
    # 页脚噪声（"Inhaltsverzeichnis" 本身就是德语里没有歧义的"目录"专属词）。
    if re.search(r"(contents|table of contents|inhaltsverzeichnis|sommaire|目录|สารบัญ|содержание|الفهرس)", lower):
        return True
    if re.search(r"^(?:annex|appendix|chapter|section|part|附录|附件|第.+[章节]|приложение|ภาคผนวก)\b.*\s\d{1,4}$", text, re.IGNORECASE):
        return True
    if re.fullmatch(r"(?:\d+(?:\.\d+)*\s+){4,}\d+(?:\.\d+)*", text):
        return True
    return False


def has_header_footer_features(text: str) -> bool:
    text = clean_text(text)
    if re.fullmatch(r"(?:page|página|seite|страница|หน้า)\s+\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?", text, re.IGNORECASE):
        return True
    if re.fullmatch(r"[-–—]?\s*\d{1,4}\s*[-–—]?", text):
        return True
    if re.search(r"\bpage\s+\d+\s+of\s+\d+\b", text, re.IGNORECASE):
        return True
    return False


def has_filename_noise(text: str) -> bool:
    text = clean_text(text)
    filename_tokens = re.findall(r"\b[A-Za-z0-9]+(?:_[A-Za-z0-9]+){2,}(?:_(?:zh|en|es|ru|de|fr|th|ar))?\b", text)
    if len(filename_tokens) >= 2 and filename_tokens[0] == filename_tokens[1]:
        return True
    return any(token.lower().endswith("_zh") and text.count(token) > 1 for token in filename_tokens)


def has_symbol_noise(text: str) -> bool:
    text = text or ""
    if "(cid:" in text or "\ufffd" in text:
        return True
    cleaned = clean_text(text)
    if not cleaned:
        return True
    if re.fullmatch(r"[\W_]+", cleaned):
        return True
    if len(cleaned) > 20 and good_char_ratio(cleaned) < 0.35:
        return True
    return False


def is_bad_eval_text(text: str) -> bool:
    return (
        has_symbol_noise(text)
        or has_directory_features(text)
        or has_header_footer_features(text)
        or has_filename_noise(text)
        or not has_language_content(text)
    )


def is_meaningful_short_row(row: dict[str, Any], text: str) -> bool:
    segment_type = str(row.get("segment_type") or "").lower()
    if segment_type in {"title", "table", "structure"} and len(text) >= 8:
        return True
    if row.get("section_no") and len(text) >= 10 and has_language_content(text):
        return True
    return False


def clean_all_eval_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    cleaned_rows: list[dict[str, Any]] = []
    removed: Counter[str] = Counter()
    seen: set[tuple[str, str, str]] = set()
    required = {"sample_id", "document_id", "language_pair", "source_lang", "target_lang", "source_text"}

    for row in rows:
        if any(not row.get(field) for field in required):
            removed["missing_required_fields"] += 1
            continue
        text = clean_text(str(row.get("source_text") or ""))
        if not text:
            removed["empty_source_text"] += 1
            continue
        if is_bad_eval_text(text):
            removed["noise_or_directory"] += 1
            continue
        if len(text) > MAX_SEGMENT_CHARS:
            removed["too_long"] += 1
            continue
        if len(text) < 30 and not is_meaningful_short_row(row, text):
            removed["too_short"] += 1
            continue
        key = (str(row["language_pair"]), str(row["document_id"]), text)
        if key in seen:
            removed["duplicate_source_text"] += 1
            continue
        seen.add(key)
        out = dict(row)
        out["source_text"] = text
        out["source_char_count"] = len(text)
        cleaned_rows.append(out)

    return cleaned_rows, removed


def section_prefix_matches(text: str, section_no: str) -> bool:
    text = clean_text(text)
    section = re.escape(str(section_no).strip())
    return bool(re.match(rf"^{section}(?:[\s.)）:：、-]|$)", text))


def section_matches_canonical(text: str, section_no: str) -> bool:
    """条款号比对统一走 canonical_section_key（2026-07-29，P 门禁统一）：
    section_prefix_matches 要求文本字面以 section_no 的原始写法开头——source
    的 section_no 是源文自己的写法（如 "Article L541-9"），中文参考译文的写法
    不同（"第L541-9条"），字面比对在条款号跨语言写法不同的语向上必然失败，
    这正是 fr 62 条对齐结果全部被拦、de Circular_Economy 3 条中招的根因。
    align_segments 早就用 canonical_section_key 做语义比对了，这里跟上，
    不再各管一套字面/语义两种判据。"""
    extracted = extract_section_no(text)
    if not extracted:
        return False
    return canonical_section_key(section_no) == canonical_section_key(extracted)


def has_strict_terminal_punctuation(text: str) -> bool:
    text = clean_text(text)
    return bool(re.search(r"[。.!?！？;；）)]$", text))


def has_complete_source_end(text: str) -> bool:
    text = clean_text(text)
    if has_strict_terminal_punctuation(text):
        return True
    return len(text) <= 100 and not re.search(r"\b(and|or|of|the|to|with|which|that|de|la|del|y|и|в|на)$", text, re.IGNORECASE)


def da_prefilter_reason(row: dict[str, Any]) -> str | None:
    required = {"sample_id", "document_id", "language_pair", "source_lang", "target_lang"}
    if any(not row.get(field) for field in required):
        return "missing_required_fields"
    if row.get("alignment_method") not in EXACT_ALIGNMENT_METHODS:
        return "non_exact_section"
    if row.get("alignment_confidence") != "high":
        return "non_high_confidence"
    if row.get("use_for_da") is not True:
        return "use_for_da_not_true"
    section_no = str(row.get("section_no") or "").strip()
    if not section_no:
        return "missing_section_no"
    source = clean_text(str(row.get("source_text") or ""))
    ref = clean_text(str(row.get("ref_text") or ""))
    if not source or not ref:
        return "missing_source_or_ref"
    if len(source) < 30:
        return "source_too_short"
    if len(ref) < 15:
        return "ref_too_short"
    if len(source) > MAX_SEGMENT_CHARS or len(ref) > MAX_SEGMENT_CHARS:
        return "too_long"
    if is_bad_eval_text(source):
        return "source_noise_or_directory"
    if is_bad_eval_text(ref):
        return "ref_noise_or_directory"
    if not section_prefix_matches(source, section_no):
        return "source_section_mismatch"
    if not section_matches_canonical(ref, section_no):
        return "ref_section_mismatch"
    ratio = len(ref) / max(len(source), 1)
    if ratio < 0.10 or ratio > 1.50:
        return "length_ratio_abnormal"
    if not has_complete_source_end(source) or not has_strict_terminal_punctuation(ref):
        return "possible_truncation"
    return None


def score_da_candidate(row: dict[str, Any]) -> float:
    source = clean_text(str(row.get("source_text") or ""))
    ref = clean_text(str(row.get("ref_text") or ""))
    ratio = len(ref) / max(len(source), 1)
    score = 10.0 - abs(ratio - 0.55)
    score += min(len(source), 240) / 240
    score += min(len(ref), 140) / 140
    if has_complete_source_end(source) and has_strict_terminal_punctuation(ref):
        score += 1
    return score


def da_dedup_key(row: dict[str, Any]) -> tuple[str, str, str]:
    # 同一文档内唯一标识一条条款：document + 作用域 + 段号（老语料无 scope，退化为原行为）。
    return (str(row.get("document_id") or ""), str(row.get("scope") or ""), str(row.get("section_no") or ""))


def clean_da_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    removed: Counter[str] = Counter()
    candidates_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        reason = da_prefilter_reason(row)
        if reason:
            removed[reason] += 1
            continue
        out = dict(row)
        out["source_text"] = clean_text(str(row["source_text"]))
        out["ref_text"] = clean_text(str(row["ref_text"]))
        out["source_char_count"] = len(out["source_text"])
        out["ref_char_count"] = len(out["ref_text"])
        out["use_for_da"] = True
        candidates_by_key[da_dedup_key(out)].append(out)

    cleaned_rows: list[dict[str, Any]] = []
    for key, candidates in candidates_by_key.items():
        best = max(candidates, key=score_da_candidate)
        cleaned_rows.append(best)
        if len(candidates) > 1:
            removed["duplicate_document_section"] += len(candidates) - 1

    cleaned_rows.sort(key=lambda row: (row["language_pair"], row["document_id"], row["order_source"]))
    return cleaned_rows, removed


def audit_da_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: Counter[str] = Counter()
    for row in rows:
        reason = da_prefilter_reason(row)
        if reason:
            failures[reason] += 1
        key = da_dedup_key(row)
        if key[2] and sum(1 for x in rows if da_dedup_key(x) == key) > 1:
            failures["duplicate_document_section"] += 1
    by_lang: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        pair = str(row.get("language_pair") or "")
        if len(by_lang[pair]) >= 5:
            continue
        by_lang[pair].append({
            "sample_id": str(row.get("sample_id") or ""),
            "section_no": str(row.get("section_no") or ""),
            "source_preview": clean_text(str(row.get("source_text") or ""))[:100],
            "ref_preview": clean_text(str(row.get("ref_text") or ""))[:100],
        })
    return {
        "passed": not failures,
        "failures": dict(sorted(failures.items())),
        "preview_by_language_pair": dict(sorted(by_lang.items())),
    }


def write_clean_summary(
    eval_dir: Path,
    all_rows: list[dict[str, Any]],
    da_rows: list[dict[str, Any]],
    all_removed: Counter[str],
    da_removed: Counter[str],
    audit: dict[str, Any],
    original_all_count: int,
    original_da_count: int,
) -> None:
    all_counts = dict(sorted(Counter(row["language_pair"] for row in all_rows).items()))
    da_counts = dict(sorted(Counter(row["language_pair"] for row in da_rows).items()))
    all_pairs = sorted(set(all_counts) | set(da_counts))
    no_da_pairs = [pair for pair in all_pairs if da_counts.get(pair, 0) == 0]
    lines = [
        "# Eval Samples Summary",
        "",
        "## 本次清洗目标",
        "",
        "- 清洗 `all_eval_samples.jsonl`，只保留适合后续翻译和 TCR 的 `source_text` 样本。",
        "- 严格清洗 `aligned_da_samples.jsonl`，只保留可用于 XCOMET-DA / COMET 有参考评分的严格对应样本。",
        "- 不调用 Qwen-Max，不运行 XCOMET，不执行 Prompt 路由，不执行 TCR。",
        "",
        "## 最终样本数",
        "",
        f"- all_eval_samples: {len(all_rows)}",
        f"- aligned_da_samples: {len(da_rows)}",
        "",
        "## 分语种 all_eval 样本数量",
        "",
    ]
    for pair, count in all_counts.items():
        lines.append(f"- {pair}: {count}")
    lines.extend(["", "## 分语种 aligned_da 样本数量", ""])
    for pair, count in da_counts.items():
        lines.append(f"- {pair}: {count}")
    if no_da_pairs:
        lines.extend(["", "## 无 DA 样本语种", ""])
        for pair in no_da_pairs:
            if pair == "th-zh":
                lines.append(f"- {pair}: 抽样自审发现疑似错位样本，按宁缺毋滥原则不生成对应 DA 文件。")
            else:
                lines.append(f"- {pair}: 没有满足 strict exact_section/high 对齐规则的样本，因此不生成对应 DA 文件。")
    lines.extend([
        "",
        "## DA 样本保留规则",
        "",
        "- 只保留 `alignment_method = exact_section` 或 `exact_section_scoped`（两者都是 1:1 精确条款号对齐）。",
        "- 只保留 `alignment_confidence = high`。",
        "- 只保留 `section_no` 非空且 source/ref 均以同一条款号开头的样本。",
        "- 删除目录项、页眉页脚、文件名重复、乱码、过短噪声、长度比例异常和明显错配样本。",
        "- 同一 `document_id + section_no` 多个候选时只保留评分最稳的一条。",
        "",
        "## 删除样本类型",
        "",
        "- 已排除 `order_based` / `page_near` / `order_near` 等非严格章节对齐 DA 样本。",
        "- 已排除 `medium` / `low` / 缺失置信度 DA 样本。",
        "- 已排除目录项、页眉页脚、文件名重复、乱码、过短噪声、长度比例异常、疑似截断和明显错配样本。",
        "- 抽样自审发现疑似错位且无法确认完全对应的语种，不保留 DA 样本。",
        "- all_eval 删除类型: "
        + (", ".join(f"{k}={v}" for k, v in sorted(all_removed.items())) or "无"),
        "- aligned_da 删除类型: "
        + (", ".join(f"{k}={v}" for k, v in sorted(da_removed.items())) or "无"),
        "",
        "## DA 自审结论",
        "",
        f"- 所有 DA 样本均为 exact_section(_scoped) + high: {'是' if all(row.get('alignment_method') in EXACT_ALIGNMENT_METHODS and row.get('alignment_confidence') == 'high' for row in da_rows) else '否'}",
        f"- 所有 DA 样本均通过条款号一致检查: {'是' if audit['passed'] else '否'}",
        "- 已排除 order_based 样本: 是",
        "- 已排除 medium / low 样本: 是",
        "- 已排除目录项和文件名重复样本: 是",
    ])
    if audit["failures"]:
        lines.append("- 自审失败项: " + ", ".join(f"{k}={v}" for k, v in audit["failures"].items()))
    lines.extend(["", "## DA 样本摘要", ""])
    for pair, previews in audit["preview_by_language_pair"].items():
        lines.append(f"### {pair}")
        lines.append("")
        for item in previews[:5]:
            lines.append(f"- sample_id: `{item['sample_id']}`")
            lines.append(f"  - section_no: `{item['section_no']}`")
            lines.append(f"  - source: {item['source_preview']}")
            lines.append(f"  - ref: {item['ref_preview']}")
        lines.append("")
    ensure_parent(eval_dir / "summary.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def clean_eval_files(args: argparse.Namespace) -> None:
    eval_dir = (PROJECT_ROOT / args.eval_dir).resolve() if not Path(args.eval_dir).is_absolute() else Path(args.eval_dir)
    all_path = eval_dir / "all_eval_samples.jsonl"
    da_path = eval_dir / "aligned_da_samples.jsonl"
    all_rows_in = read_jsonl(all_path)
    da_rows_in = read_jsonl(da_path)

    all_rows, all_removed = clean_all_eval_rows(all_rows_in)
    da_rows, da_removed = clean_da_rows(da_rows_in)
    audit = audit_da_rows(da_rows)
    if not audit["passed"]:
        raise RuntimeError(f"DA self-audit failed after cleaning: {audit['failures']}")

    write_jsonl(all_path, all_rows)
    write_jsonl(da_path, da_rows)
    write_by_language(eval_dir, "all_eval_samples", all_rows)
    write_by_language(eval_dir, "aligned_da_samples", da_rows)
    write_clean_summary(eval_dir, all_rows, da_rows, all_removed, da_removed, audit, len(all_rows_in), len(da_rows_in))

    print(json.dumps({
        "eval_dir": str(eval_dir),
        "all_eval_samples": len(all_rows),
        "aligned_da_samples": len(da_rows),
        "all_counts_by_language_pair": dict(sorted(Counter(row["language_pair"] for row in all_rows).items())),
        "aligned_counts_by_language_pair": dict(sorted(Counter(row["language_pair"] for row in da_rows).items())),
        "all_removed": dict(sorted(all_removed.items())),
        "da_removed": dict(sorted(da_removed.items())),
        "da_audit": audit,
    }, ensure_ascii=False, indent=2))


def read_jsonl_for_split(path: Path, required_fields: set[str], text_fields: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any], Counter[str]]:
    rows: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    seen_sample_ids: set[str] = set()
    validation = {
        "path": str(path),
        "legal_jsonl": True,
        "total_lines": 0,
        "valid_rows": 0,
        "issues": {},
    }

    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            validation["total_lines"] += 1
            stripped = line.strip()
            if not stripped:
                excluded["empty_line"] += 1
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                validation["legal_jsonl"] = False
                excluded["invalid_json"] += 1
                continue
            if not isinstance(row, dict):
                validation["legal_jsonl"] = False
                excluded["non_object_json"] += 1
                continue
            if any(not row.get(field) for field in required_fields):
                excluded["missing_required_fields"] += 1
                continue
            if any(not str(row.get(field) or "").strip() for field in text_fields):
                excluded["empty_text_field"] += 1
                continue
            sample_id = str(row.get("sample_id") or "")
            if sample_id in seen_sample_ids:
                excluded["duplicate_sample_id"] += 1
                continue
            seen_sample_ids.add(sample_id)
            rows.append(row)

    validation["valid_rows"] = len(rows)
    validation["issues"] = dict(sorted(excluded.items()))
    return rows, validation, excluded


def length_bucket(row: dict[str, Any]) -> str:
    n = int(row.get("source_char_count") or len(str(row.get("source_text") or "")))
    if n < 80:
        return "short"
    if n <= 300:
        return "medium"
    return "long"


def split_stratum_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("document_id") or ""),
        str(row.get("segment_type") or "unknown"),
        length_bucket(row),
        "has_section" if row.get("section_no") else "no_section",
    )


def stratified_sample(rows: list[dict[str, Any]], max_per_language: int, seed: int) -> list[dict[str, Any]]:
    by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_pair[str(row["language_pair"])].append(row)

    selected: list[dict[str, Any]] = []
    for pair, pair_rows in sorted(by_pair.items()):
        ordered_rows = sorted(pair_rows, key=lambda row: str(row.get("sample_id") or ""))
        if len(ordered_rows) <= max_per_language:
            selected.extend(ordered_rows)
            continue

        rng = random.Random(f"{seed}:{pair}:{max_per_language}")
        strata: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in ordered_rows:
            strata[split_stratum_key(row)].append(row)
        for stratum_rows in strata.values():
            rng.shuffle(stratum_rows)
        stratum_keys = sorted(strata)
        rng.shuffle(stratum_keys)

        pair_selected: list[dict[str, Any]] = []
        while len(pair_selected) < max_per_language and stratum_keys:
            next_keys: list[tuple[str, str, str, str]] = []
            for key in stratum_keys:
                if not strata[key]:
                    continue
                pair_selected.append(strata[key].pop())
                if len(pair_selected) >= max_per_language:
                    break
                if strata[key]:
                    next_keys.append(key)
            stratum_keys = next_keys
            rng.shuffle(stratum_keys)

        pair_selected.sort(key=lambda row: str(row.get("sample_id") or ""))
        selected.extend(pair_selected)

    selected.sort(key=lambda row: (str(row.get("language_pair") or ""), str(row.get("sample_id") or "")))
    return selected


SOURCE_ONLY_SPLIT = "source_only_300_by_lang"
REFERENCE_WITH_REF_SPLIT = "reference_with_ref_300_by_lang"
MAX_REFERENCE_ROWS_PER_LANGUAGE = 300

SOURCE_ONLY_DROP_FIELDS = {
    "ref_text",
    "ref_char_count",
    "page_ref",
    "order_ref",
    "alignment_method",
    "alignment_confidence",
    "ref_source",
    "reference_source",
    "da_source_priority",
    "original_sample_id",
    "ref_type",
    "is_summary_ref",
    "ref_is_summary",
    "is_machine_ref",
    "machine_ref",
    "ref_is_machine_translation",
}


def add_source_only_split_fields(rows: list[dict[str, Any]], dataset_base_version: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = {key: value for key, value in row.items() if key not in SOURCE_ONLY_DROP_FIELDS}
        item["dataset_base_version"] = dataset_base_version
        item["split_name"] = SOURCE_ONLY_SPLIT
        item["split_role"] = "source_only"
        item["use_for_translation"] = True
        item["reference_available"] = bool(row.get("ref_text"))
        item.pop("use_for_da", None)
        out.append(item)
    return out


def add_reference_split_fields(rows: list[dict[str, Any]], dataset_base_version: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["dataset_base_version"] = dataset_base_version
        item["split_name"] = REFERENCE_WITH_REF_SPLIT
        item["split_role"] = "reference_with_ref"
        item["use_for_da"] = True
        out.append(item)
    return out


def clean_split_dir(path: Path, main_file: str, suffix: str) -> None:
    if path.exists():
        target = path / main_file
        if target.exists():
            target.unlink()
        by_lang = path / "by_lang"
        if by_lang.exists():
            for old_file in by_lang.glob(f"*_{suffix}.jsonl"):
                old_file.unlink()
    path.mkdir(parents=True, exist_ok=True)


def write_split_jsonl(split_dir: Path, main_file: str, rows: list[dict[str, Any]], by_lang_suffix: str) -> None:
    clean_split_dir(split_dir, main_file, by_lang_suffix)
    write_jsonl(split_dir / main_file, rows)
    write_by_language(split_dir, by_lang_suffix, rows)


def count_by_pair(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row["language_pair"]) for row in rows).items()))


def validate_written_jsonl(paths: list[Path]) -> dict[str, Any]:
    result = {"all_legal": True, "files": {}}
    for path in paths:
        count = 0
        legal = True
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    legal = False
                    continue
                if not isinstance(parsed, dict):
                    legal = False
                count += 1
        result["files"][str(path)] = {"legal_jsonl": legal, "rows": count}
        if not legal:
            result["all_legal"] = False
    return result


def split_reach_status(base_counts: dict[str, int], split_counts: dict[str, int], target: int) -> dict[str, dict[str, Any]]:
    status: dict[str, dict[str, Any]] = {}
    for pair, base_count in sorted(base_counts.items()):
        expected = min(base_count, target)
        actual = split_counts.get(pair, 0)
        status[pair] = {
            "base_count": base_count,
            "target": target,
            "expected": expected,
            "actual": actual,
            "reached": actual == expected,
        }
    return status


def write_split_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    json_summary = output_dir / "split_summary.json"
    if json_summary.exists():
        json_summary.unlink()
    lines = [
        "# Split Summary",
        "",
        f"- dataset_base_version: `{summary['dataset_base_version']}`",
        f"- random_seed: {summary['seed']}",
        f"- max_per_language_pair: {summary['max_per_language_pair']}",
        "",
        "## Input Files",
        "",
    ]
    for key, value in summary["input_files"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend([
        "",
        "## Validation Result",
        "",
        f"- reference input legal JSONL: {summary['validation_result']['reference_input']['legal_jsonl']}",
        f"- output JSONL legal: {summary['validation_result']['outputs']['all_legal']}",
        "",
        "## Total Samples",
        "",
        f"- total_reference_input_samples: {summary['total_reference_input_samples']}",
        f"- selected_samples: {summary['selected_samples']}",
        "",
        f"## {SOURCE_ONLY_SPLIT}",
        "",
        f"- total: {summary['splits'][SOURCE_ONLY_SPLIT]['total']}",
    ])
    for pair, count in summary["splits"][SOURCE_ONLY_SPLIT]["counts_by_language_pair"].items():
        lines.append(f"- {pair}: {count}")
    lines.extend(["", f"## {REFERENCE_WITH_REF_SPLIT}", "", f"- total: {summary['splits'][REFERENCE_WITH_REF_SPLIT]['total']}"])
    for pair, count in summary["splits"][REFERENCE_WITH_REF_SPLIT]["counts_by_language_pair"].items():
        lines.append(f"- {pair}: {count}")
    lines.extend(["", "## Excluded Samples", ""])
    for source, reasons in summary["excluded_samples"].items():
        reason_text = ", ".join(f"{k}={v}" for k, v in reasons.items()) if reasons else "none"
        lines.append(f"- {source}: {reason_text}")
    lines.extend(["", "## Language Target Status", ""])
    for pair, item in summary["language_target_status"][SOURCE_ONLY_SPLIT].items():
        lines.append(f"- {pair}: actual={item['actual']}, expected={item['expected']}, reached={item['reached']}")
    lines.extend([
        "",
        "## Acceptance Notes",
        "",
        f"- `{SOURCE_ONLY_SPLIT}` 只用于翻译和 TCR，不包含 ref_text。",
        f"- `{REFERENCE_WITH_REF_SPLIT}` 用于 DA/COMET 参考译文查找。",
        "- 两套 split 必须通过 sample_id、da_reference_id、source_text 保持一一对应。",
        "- 某语种可信参考译文不足 300 条时，保留全部可用配对样本。",
    ])
    ensure_parent(output_dir / "split_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_splits(args: argparse.Namespace) -> None:
    dataset_base_version = "reference_300_by_lang_v1"
    aligned_da_path = (PROJECT_ROOT / args.aligned_da).resolve() if not Path(args.aligned_da).is_absolute() else Path(args.aligned_da)
    output_dir = (PROJECT_ROOT / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir)
    if args.max_per_language < 1:
        raise ValueError("--max-per-language must be >= 1")

    da_required = {
        "sample_id",
        "document_id",
        "language_pair",
        "source_lang",
        "target_lang",
        "source_text",
        "ref_text",
        "alignment_method",
        "alignment_confidence",
        "use_for_da",
    }
    da_rows, da_validation, da_input_excluded = read_jsonl_for_split(aligned_da_path, da_required, {"source_text", "ref_text"})

    selected = stratified_sample(da_rows, args.max_per_language, args.seed)
    source_only = add_source_only_split_fields(selected, dataset_base_version)
    reference_rows = add_reference_split_fields(selected, dataset_base_version)

    source_only_dir = output_dir / SOURCE_ONLY_SPLIT
    reference_dir = output_dir / REFERENCE_WITH_REF_SPLIT
    stale_json_summary = output_dir / "split_summary.json"
    if stale_json_summary.exists():
        stale_json_summary.unlink()
    write_split_jsonl(source_only_dir, "all_samples_source_only.jsonl", source_only, "samples_source_only")
    write_split_jsonl(reference_dir, "all_samples_with_reference.jsonl", reference_rows, "samples_with_reference")

    output_jsonl_paths = [
        source_only_dir / "all_samples_source_only.jsonl",
        reference_dir / "all_samples_with_reference.jsonl",
    ]
    output_jsonl_paths.extend(sorted((source_only_dir / "by_lang").glob("*.jsonl")))
    output_jsonl_paths.extend(sorted((reference_dir / "by_lang").glob("*.jsonl")))

    base_counts = count_by_pair(da_rows)
    summary = {
        "dataset_base_version": dataset_base_version,
        "seed": args.seed,
        "max_per_language_pair": args.max_per_language,
        "input_files": {
            "reference_input": str(aligned_da_path),
        },
        "validation_result": {
            "reference_input": da_validation,
            "outputs": validate_written_jsonl(output_jsonl_paths),
        },
        "total_reference_input_samples": len(da_rows),
        "selected_samples": len(selected),
        "splits": {
            SOURCE_ONLY_SPLIT: {
                "total": len(source_only),
                "max_per_language_pair": args.max_per_language,
                "counts_by_language_pair": count_by_pair(source_only),
                "contains_ref_text": False,
            },
            REFERENCE_WITH_REF_SPLIT: {
                "total": len(reference_rows),
                "max_per_language_pair": args.max_per_language,
                "counts_by_language_pair": count_by_pair(reference_rows),
                "contains_ref_text": True,
            },
        },
        "excluded_samples": {
            "reference_input_validation": dict(sorted(da_input_excluded.items())),
        },
        "language_target_status": {
            SOURCE_ONLY_SPLIT: split_reach_status(base_counts, count_by_pair(source_only), args.max_per_language),
        },
        "notes": [
            f"{SOURCE_ONLY_SPLIT} removes ref_text and is used for translation/TCR.",
            f"{REFERENCE_WITH_REF_SPLIT} keeps ref_text and is used for DA/COMET scoring.",
            "Rows are selected from reference-capable samples only.",
        ],
    }
    write_split_summary(output_dir, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_from_raw(args: argparse.Namespace) -> None:
    raw_dir = (PROJECT_ROOT / args.raw_dir).resolve() if not Path(args.raw_dir).is_absolute() else Path(args.raw_dir)
    output_dir = (PROJECT_ROOT / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir)
    clear_raw_eval_outputs(output_dir)
    groups = load_raw_groups(raw_dir)
    if not groups:
        raise RuntimeError(f"No source/reference PDF groups found under {raw_dir}")

    # 隔离重建：只处理指定语向/文档，其余语向的既有语料一行都不碰。
    if args.only_language_pair:
        wanted = {x.strip() for x in args.only_language_pair.split(",") if x.strip()}
        groups = [g for g in groups if g["language_pair"] in wanted]
    if args.only_doc_id:
        wanted_docs = {x.strip() for x in args.only_doc_id.split(",") if x.strip()}
        groups = [g for g in groups if g["document_id"] in wanted_docs]
    if not groups:
        raise RuntimeError("No PDF groups left after --only-language-pair / --only-doc-id filtering")

    all_samples: list[dict[str, Any]] = []
    aligned_samples: list[dict[str, Any]] = []
    source_segments_all: list[dict[str, Any]] = []
    ref_segments_all: list[dict[str, Any]] = []
    filtered_count = 0
    notes: list[str] = []

    for group in groups:
        source_pdf = Path(group["source_pdf"])
        reference_pdf = Path(group["reference_pdf"])
        print(f"[PDF] {group['language_pair']} {group['document_id']}", flush=True)
        source_segments, source_filtered, source_notes = parse_pdf_segments(
            source_pdf,
            group["document_id"],
            group["language_pair"],
            group["source_lang"],
            min_chars=args.min_source_chars,
            max_chars=args.max_segment_chars,
        )
        ref_segments, ref_filtered, ref_notes = parse_pdf_segments(
            reference_pdf,
            group["document_id"],
            group["language_pair"],
            group["target_lang"],
            min_chars=args.min_ref_chars,
            max_chars=args.max_segment_chars,
        )
        filtered_count += source_filtered + ref_filtered
        notes.extend(source_notes + ref_notes)
        source_segments_all.extend(source_segments)
        ref_segments_all.extend(ref_segments)
        all_samples.extend(make_all_sample(segment, group) for segment in source_segments)
        aligned_samples.extend(align_segments(source_segments, ref_segments, group, args.min_source_chars))

    all_samples.sort(key=lambda row: (row["language_pair"], row["document_id"], row["order_source"]))
    aligned_samples.sort(key=lambda row: (row["language_pair"], row["document_id"], row["order_source"]))

    write_jsonl(output_dir / "all_eval_samples.jsonl", all_samples)
    write_jsonl(output_dir / "aligned_da_samples.jsonl", aligned_samples)
    write_by_language(output_dir, "all_eval_samples", all_samples)
    write_by_language(output_dir, "aligned_da_samples", aligned_samples)

    summary = {
        "total_documents": len(groups),
        "total_source_segments": len(source_segments_all),
        "total_reference_segments": len(ref_segments_all),
        "total_all_eval_samples": len(all_samples),
        "total_aligned_da_samples": len(aligned_samples),
        "counts_by_language_pair": dict(sorted(Counter(row["language_pair"] for row in all_samples).items())),
        "aligned_counts_by_language_pair": dict(sorted(Counter(row["language_pair"] for row in aligned_samples).items())),
        "alignment_method_distribution": dict(sorted(Counter(row["alignment_method"] for row in aligned_samples).items())),
        "segment_type_distribution": dict(sorted(Counter(row["segment_type"] for row in all_samples).items())),
        "filtered_segment_count": filtered_count,
        "notes": notes,
    }
    write_summary(output_dir, summary)
    print(json.dumps({"output_dir": str(output_dir), **summary}, ensure_ascii=False, indent=2))


def prepare_existing_da_pairs(args: argparse.Namespace) -> None:
    if not args.input or not args.output:
        raise SystemExit("--input and --output are required unless --mode from_raw or --mode clean_eval_files is used.")
    rows = read_jsonl(args.input)
    out = []
    skipped = 0
    for idx, row in enumerate(rows, 1):
        source = pick_first(row, ["source", "source_text", "text", "src"])
        hypothesis = pick_first(row, ["hypothesis", "mt_text", "new_translation", "translation", "translated_text"])
        reference = pick_first(row, ["reference", "ref_text", "ref_candidate_text", "target_text"])
        if not source or not hypothesis or len(reference) < args.min_ref_chars:
            skipped += 1
            continue
        out.append({
            "sample_id": row.get("sample_id") or row_key(row, idx),
            "source_lang": row.get("source_lang") or row.get("lang") or args.source_lang,
            "target_lang": row.get("target_lang") or args.target_lang,
            "source": source,
            "hypothesis": hypothesis,
            "reference": reference,
            "doc_id": row.get("doc_id", ""),
            "seg_id": row.get("seg_id", ""),
        })

    write_jsonl(args.output, out)
    print(json.dumps({"input": args.input, "output": args.output, "rows": len(out), "skipped": skipped}, ensure_ascii=False, indent=2))


# ---- canonical_section_key 单测（P1，2026-07-29）----
CANONICAL_CASES = [
    ("Article 1", "第1条", True, "fr/zh 顶层条款对等——P1 要解决的核心问题"),
    ("Article 1", "第 1 条", True, "zh 侧带空格，不应影响归一化"),
    ("Article 1", "第一条", True, "zh 侧中文数字，不是阿拉伯数字，同样要对等"),
    ("Article 1", "Article 2", False, "同类型不同号，不能对等"),
    ("Article 1", "第2条", False, "跨语言不同号，不能对等"),
    ("§ 22", "第22条", True, "de 预留：德语 § 与中文条是同一级条款"),
    ("Artículo 2°", "第 2 条", True, "es：带序数符号 ° 的条款号"),
    ("Статья 5", "第5条", True, "ru 文字型条款号（GOST 罕见，仍需支持）"),
    ("12.1", "12.1", True, "en/ru 纯数字体系——必须是恒等变换"),
    ("3.2", "3.1", False, "纯数字体系里不同号不能对等"),
    ("第二章", "第三章", False, "章级容器，不同号不能对等"),
    ("第二章", "第2条", False, "章级容器与条级条款不同类型，即使数字部分相同也不能对等"),
    ("А.1", "A.1", True, "ru GOST：西里尔附录字母 А(U+0410) 与拉丁 A(U+0041) 形近，须同key"),
    ("А.1.1", "A.1.2", False, "西里尔前缀转写正确的前提下，数字不同仍不能对等"),
    ("Article L541-9", "第L541-9条", True, "fr 环境法典字母条款号：Article L.../第...条 是同一编码"),
    ("Article L541-9-3-1", "第L541-9-3-1条", True, "多级连字符编码也要对等"),
    ("Article L541-9", "第L541-10条", False, "编码不同不能对等"),
    ("Article L541-9", "第L541-9-1条", False, "同前缀不同级别（-9 vs -9-1）不能对等"),
]


def _selftest_canonical() -> int:
    bad = 0
    print("=== canonical_section_key 正反用例 ===")
    for a, b, want_equal, why in CANONICAL_CASES:
        ka, kb = canonical_section_key(a), canonical_section_key(b)
        got_equal = ka == kb
        ok = got_equal == want_equal
        bad += not ok
        print(f"  {'OK ' if ok else 'FAIL'} {a!r} vs {b!r} -> {ka} / {kb}  "
              f"(期望{'相等' if want_equal else '不等'}, 实得{'相等' if got_equal else '不等'})  {why}")
    print(f"\n{'全部通过' if not bad else f'{bad} 个用例不通过'}")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description="Prepare source/hypothesis/reference triples for server-side XCOMET-DA/COMET scoring.")
    ap.add_argument("--mode", choices=["prepare_da_pairs", "from_raw", "clean_eval_files", "build_splits", "selftest_canonical"], default="prepare_da_pairs")
    ap.add_argument("--input", help="Aligned JSONL or rows containing reference text.")
    ap.add_argument("--output", help="DA input JSONL output.")
    ap.add_argument("--aligned-da", default="data/eval/aligned_da_samples.jsonl")
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument("--only-language-pair", default="", help="逗号分隔，仅 from_raw：只重建这些语向（如 en-zh）。")
    ap.add_argument("--only-doc-id", default="", help="逗号分隔，仅 from_raw：只重建这些 document_id。")
    ap.add_argument("--eval-dir", default="data/eval")
    ap.add_argument("--output-dir", default="data/eval")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-per-language", type=int, default=MAX_REFERENCE_ROWS_PER_LANGUAGE)
    ap.add_argument("--source-lang", default="en")
    ap.add_argument("--target-lang", default="zh")
    ap.add_argument("--min-ref-chars", type=int, default=2)
    ap.add_argument("--min-source-chars", type=int, default=30)
    ap.add_argument("--max-segment-chars", type=int, default=MAX_SEGMENT_CHARS)
    args = ap.parse_args()

    if args.mode == "from_raw":
        build_from_raw(args)
    elif args.mode == "clean_eval_files":
        clean_eval_files(args)
    elif args.mode == "build_splits":
        build_splits(args)
    elif args.mode == "selftest_canonical":
        raise SystemExit(1 if _selftest_canonical() else 0)
    else:
        prepare_existing_da_pairs(args)


if __name__ == "__main__":
    main()
