# 共享工具：Prompt 模板、术语注入文本和可复现的分级路由规则。
# 本文件只构造实验输入或翻译消息，不执行模型调用。

from __future__ import annotations

import re
from typing import Any

from scripts.common.lang import lang_name, normalize_lang
from scripts.common.termbase import (
    count_core_high,
    required_target_terms,
    review_terms as collect_review_terms,
    soft_terms as collect_soft_terms,
)

GRADED_PROMPT_MODES = ["lightweight", "structure", "strict_term", "natural_legal"]
RETRY_PROMPT_MODE = "retry_repair"

STRUCTURED_SEGMENT_TYPES = {"table", "list", "title", "note"}
DISPLAY_LANG_NAME = {
    "ar": "阿拉伯语",
    "de": "德语",
    "en": "英语",
    "es": "西班牙语",
    "fr": "法语",
    "ru": "俄语",
    "th": "泰语",
    "zh": "中文",
}
LEGAL_KEYWORDS = [
    "definition", "definitions", "requirement", "requirements", "certification",
    "approval", "test", "testing", "conformity", "compliance", "shall", "must",
    "definitionen", "anforderung", "anforderungen", "genehmigung", "prüfung",
    "essai", "exigence", "homologation", "conformité",
    "ensayo", "requisito", "homologación", "conformidad",
    "испыт", "требован", "одобр", "соответств",
    "تعريف", "متطلبات", "مطابقة", "اختبار", "اعتماد",
    "ข้อกำหนด", "การทดสอบ", "การรับรอง",
]

UNIT_RE = re.compile(
    r"(?i)(?:\b\d+(?:[.,]\d+)?\s?(?:km/h|kph|kg|g|mg|mm|cm|m|km|kw|w|v|a|hz|n|nm|"
    r"db|pa|kpa|mpa|bar|s|ms|h|min|%|°c|celsius)\b)"
)
NUMBERING_RE = re.compile(r"(?<![A-Za-z0-9])(?:\d+(?:[./-]\d+)+|\d+[.)])")
CLAUSE_RE = re.compile(r"(?<![A-Za-z0-9])(?:\d+(?:\.\d+){1,4}|[A-Za-z]?\d+/\d+)(?![A-Za-z0-9])")
STANDARD_RE = re.compile(
    r"(?i)\b(?:UN\s*R|UN/ECE|UNECE|ECE|ISO|IEC|SAE|FMVSS|SASO|GSO|GB/T|GB|"
    r"Regulation\s+No\.?|R\d{2,3})\b"
)
CERTIFICATE_RE = re.compile(
    r"(?i)(?:certificate|approval\s+number|certificat|genehmigungsnummer|"
    r"n[uú]mero\s+de\s+homologaci[oó]n|номер|شهادة|证书|认证编号)"
)
LIST_MARKER_RE = re.compile(r"(?m)^\s*(?:[-*•·]|\d+[.)]|[A-Za-z][.)])\s+")


def _unique_text(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _display_lang_name(code: str | None) -> str:
    normalized = normalize_lang(code)
    return DISPLAY_LANG_NAME.get(normalized, lang_name(code))


def _term_pairs(terms: list[dict[str, Any]]) -> list[str]:
    pairs: list[str] = []
    seen: set[tuple[str, str]] = set()
    for term in terms:
        source = str(term.get("source_term") or "").strip()
        target = str(term.get("target_term") or "").strip()
        if not source or not target:
            continue
        key = (source, target)
        if key in seen:
            continue
        seen.add(key)
        priority = str(term.get("priority") or "").strip() or "-"
        status = str(term.get("status") or "").strip() or "-"
        pairs.append(f"- {source} => {target} [{priority}/{status}]")
    return pairs


def _format_targets(targets: list[str]) -> str:
    targets = _unique_text(targets)
    if not targets:
        return "- 无强制术语。"
    return "\n".join(f"- {target}" for target in targets)


def format_term_table(matched_terms: list[dict[str, Any]], scope: str = "hard") -> str:
    if scope == "hard":
        targets = required_target_terms(matched_terms)
        return _format_targets(targets)
    pairs = _term_pairs(matched_terms)
    return "\n".join(pairs) if pairs else "- 无匹配术语。"


def _format_reference_terms(terms: list[dict[str, Any]], empty_text: str) -> str:
    pairs = _term_pairs(terms)
    return "\n".join(pairs) if pairs else f"- {empty_text}"


def _term_constraint_block(
    required_targets: list[str],
    review_terms: list[dict[str, Any]] | None = None,
    soft_terms: list[dict[str, Any]] | None = None,
) -> str:
    return f"""术语约束：
required_target_terms（硬约束，必须使用下列指定中文译法；如为空则无强制术语）：
{_format_targets(required_targets)}

review_terms（仅供参考，不计入硬约束）：
{_format_reference_terms(review_terms or [], "无参考术语。")}

soft_terms（可选参考，不计入硬约束）：
{_format_reference_terms(soft_terms or [], "无可选术语。")}"""


def _common_output_rules(target_name: str) -> str:
    return f"""通用要求：
1. 目标语言为{target_name}。
2. 保持法规、标准、技术文件的正式语体。
3. 保留数字、单位、编号、标准号、公式和符号。
4. 不添加解释，不遗漏内容。
5. 只输出译文，不输出分析。"""


def no_term_general_template(source_text: str, source_lang: str, target_lang: str = "zh") -> str:
    source_name = _display_lang_name(source_lang)
    target_name = _display_lang_name(target_lang)
    return f"""任务：请将以下{source_name}法规/标准文本翻译成{target_name}。

{_common_output_rules(target_name)}

风格要求：
- 使用准确、正式、自然的法规中文表达。
- 保持原文信息顺序和义务、禁止、许可、条件等逻辑。

原文：
{source_text}

只输出译文。"""


def term_general_template(
    source_text: str,
    source_lang: str,
    target_lang: str = "zh",
    required_targets: list[str] | None = None,
    review_terms: list[dict[str, Any]] | None = None,
    soft_terms: list[dict[str, Any]] | None = None,
) -> str:
    source_name = _display_lang_name(source_lang)
    target_name = _display_lang_name(target_lang)
    return f"""任务：请将以下{source_name}法规/标准文本翻译成{target_name}。

{_common_output_rules(target_name)}

{_term_constraint_block(required_targets or [], review_terms, soft_terms)}

统一策略：
- 所有样本均使用本通用模板，不根据长度、结构或术语数量切换模式。
- required_target_terms 中的中文译法必须在译文中准确使用，不得用同义词替换。
- review_terms 和 soft_terms 只作为辅助参考。

原文：
{source_text}

只输出译文。"""


def lightweight_template(
    source_text: str,
    source_lang: str,
    target_lang: str = "zh",
    required_targets: list[str] | None = None,
    review_terms: list[dict[str, Any]] | None = None,
    soft_terms: list[dict[str, Any]] | None = None,
) -> str:
    source_name = _display_lang_name(source_lang)
    target_name = _display_lang_name(target_lang)
    return f"""任务：以 lightweight 模式将以下简短{source_name}法规/标准文本翻译成{target_name}。

{_common_output_rules(target_name)}

{_term_constraint_block(required_targets or [], review_terms, soft_terms)}

lightweight 要求：
- 译文简短、直接、自然。
- 不扩写短语，不补充背景说明。
- 如存在 required_target_terms，仍须准确使用。

原文：
{source_text}

只输出译文。"""


def structure_template(
    source_text: str,
    source_lang: str,
    target_lang: str = "zh",
    required_targets: list[str] | None = None,
    review_terms: list[dict[str, Any]] | None = None,
    soft_terms: list[dict[str, Any]] | None = None,
) -> str:
    source_name = _display_lang_name(source_lang)
    target_name = _display_lang_name(target_lang)
    return f"""任务：以 structure 模式将以下结构化{source_name}法规/标准文本翻译成{target_name}。

{_common_output_rules(target_name)}

{_term_constraint_block(required_targets or [], review_terms, soft_terms)}

structure 要求：
- 严格保持编号、字段名、表格行、项目符号、单位、符号和标准号。
- 不补充、不扩写、不重排字段顺序。
- 结构稳定性优先于语言润色。
- 对短字段、证书号、条款号和列表项保持原有结构。

原文：
{source_text}

只输出译文。"""


def strict_term_template(
    source_text: str,
    source_lang: str,
    target_lang: str = "zh",
    required_targets: list[str] | None = None,
    review_terms: list[dict[str, Any]] | None = None,
    soft_terms: list[dict[str, Any]] | None = None,
) -> str:
    source_name = _display_lang_name(source_lang)
    target_name = _display_lang_name(target_lang)
    return f"""任务：以 strict_term 模式将以下{source_name}法规/标准文本翻译成{target_name}。

{_common_output_rules(target_name)}

{_term_constraint_block(required_targets or [], review_terms, soft_terms)}

strict_term 要求：
- hard required terms 必须逐项落实。
- 目标译文必须包含 required_target_terms 中的指定中文译法。
- 不得用同义词或近义表达替换 required_target_terms。
- 同一术语出现多次时，译法必须保持一致。
- 在满足硬术语约束的基础上兼顾法规表达。

原文：
{source_text}

只输出译文。"""


def natural_legal_template(
    source_text: str,
    source_lang: str,
    target_lang: str = "zh",
    required_targets: list[str] | None = None,
    review_terms: list[dict[str, Any]] | None = None,
    soft_terms: list[dict[str, Any]] | None = None,
) -> str:
    source_name = _display_lang_name(source_lang)
    target_name = _display_lang_name(target_lang)
    return f"""任务：以 natural_legal 模式将以下{source_name}法规/标准正文翻译成{target_name}。

{_common_output_rules(target_name)}

{_term_constraint_block(required_targets or [], review_terms, soft_terms)}

natural_legal 要求：
- 法规中文表达自然、正式、准确。
- 保持义务、禁止、许可、条件等法律逻辑。
- 使用 required_target_terms，但不要为了堆叠术语牺牲中文可读性。
- 保持原文论述层次和技术限制条件。

原文：
{source_text}

只输出译文。"""


def retry_repair_template(
    source_text: str,
    current_translation: str,
    failed_terms: list[dict[str, Any]],
    source_lang: str,
    target_lang: str = "zh",
) -> str:
    source_name = _display_lang_name(source_lang)
    target_name = _display_lang_name(target_lang)
    failed_text = _format_reference_terms(failed_terms, "无 failed_terms。")
    return f"""任务：以 retry_repair 模式修复一条{source_name}->{target_name}译文中的术语错误。

修复要求：
- 只修复 failed_terms 对应的错误术语。
- 尽量保持当前译文结构和无关内容不变。
- 不重写无关句子，不添加解释。
- 只输出修复后的译文，不输出分析。

原文：
{source_text}

当前译文：
{current_translation}

failed_terms：
{failed_text}

只输出修复后的译文。"""


def detect_route_features(
    source_text: str,
    source_char_count: int | None = None,
    segment_type: str | None = None,
    section_no: Any = None,
    matched_high_count: int = 0,
    matched_total_count: int = 0,
    required_targets: list[str] | None = None,
) -> dict[str, Any]:
    text = source_text or ""
    char_count = source_char_count if source_char_count is not None else len(text)
    segment = str(segment_type or "").strip().lower()
    required_count = len(required_targets or [])

    colon_count = text.count(":") + text.count("：")
    semicolon_count = text.count(";") + text.count("；")
    table_delimiter_count = text.count("|") + text.count("\t")
    numbering_count = len(NUMBERING_RE.findall(text))
    clause_count = len(CLAUSE_RE.findall(text))
    parentheses_count = sum(text.count(ch) for ch in ["(", ")", "（", "）", "[", "]", "【", "】"])
    unit_count = len(UNIT_RE.findall(text))
    standard_count = len(STANDARD_RE.findall(text))
    certificate_count = len(CERTIFICATE_RE.findall(text))
    list_marker_count = len(LIST_MARKER_RE.findall(text))
    legal_keyword_count = sum(1 for keyword in LEGAL_KEYWORDS if keyword.lower() in text.lower())

    signal_flags = {
        "has_colon": colon_count > 0,
        "has_semicolon": semicolon_count > 0,
        "has_table_delimiter": table_delimiter_count > 0,
        "has_numbering": numbering_count > 0,
        "has_clause_no": bool(section_no) or clause_count > 0,
        "has_parentheses": parentheses_count > 0,
        "has_unit": unit_count > 0,
        "has_standard_no": standard_count > 0,
        "has_certificate_no": certificate_count > 0,
        "has_list_marker": list_marker_count > 0,
    }
    structure_signal_count = sum(1 for value in signal_flags.values() if value)
    structure_marker_count = (
        colon_count + semicolon_count + table_delimiter_count + numbering_count + clause_count
        + parentheses_count + unit_count + standard_count + certificate_count + list_marker_count
    )
    structured_segment_with_signal = segment in STRUCTURED_SEGMENT_TYPES and structure_signal_count >= 1
    field_like_short = char_count <= 120 and (
        signal_flags["has_colon"]
        or signal_flags["has_certificate_no"]
        or signal_flags["has_standard_no"]
        or signal_flags["has_clause_no"]
        or signal_flags["has_list_marker"]
    )
    many_structure_markers = structure_signal_count >= 3 or structure_marker_count >= 5
    simple_short_text = (
        char_count <= 120
        and matched_high_count == 0
        and structure_signal_count <= 1
        and segment not in STRUCTURED_SEGMENT_TYPES
    )

    return {
        "source_char_count": char_count,
        "segment_type": segment,
        "section_no": section_no,
        "matched_high_count": matched_high_count,
        "matched_total_count": matched_total_count,
        "required_target_term_count": required_count,
        "colon_count": colon_count,
        "semicolon_count": semicolon_count,
        "table_delimiter_count": table_delimiter_count,
        "numbering_count": numbering_count,
        "clause_count": clause_count,
        "parentheses_count": parentheses_count,
        "unit_count": unit_count,
        "standard_count": standard_count,
        "certificate_count": certificate_count,
        "list_marker_count": list_marker_count,
        "legal_keyword_count": legal_keyword_count,
        "structure_signal_count": structure_signal_count,
        "structure_marker_count": structure_marker_count,
        "structured_segment_with_signal": structured_segment_with_signal,
        "field_like_short": field_like_short,
        "many_structure_markers": many_structure_markers,
        "simple_short_text": simple_short_text,
        **signal_flags,
    }


def route_prompt_mode(
    source_text: str,
    matched_terms: list[dict[str, Any]],
    source_char_count: int | None = None,
    segment_type: str | None = None,
    section_no: Any = None,
    required_targets: list[str] | None = None,
    retry_needed: bool = False,
) -> tuple[str, str, dict[str, Any]]:
    if retry_needed:
        return RETRY_PROMPT_MODE, "retry_repair: retry_needed=true", {}

    required = required_targets if required_targets is not None else required_target_terms(matched_terms)
    matched_high_count = count_core_high(matched_terms)
    features = detect_route_features(
        source_text=source_text,
        source_char_count=source_char_count,
        segment_type=segment_type,
        section_no=section_no,
        matched_high_count=matched_high_count,
        matched_total_count=len(matched_terms),
        required_targets=required,
    )

    if (
        features["structured_segment_with_signal"]
        or features["many_structure_markers"]
        or features["field_like_short"]
    ):
        reason = (
            "structure: structural segment or dense structural markers "
            f"(signals={features['structure_signal_count']}, markers={features['structure_marker_count']})"
        )
        return "structure", reason, features

    if matched_high_count >= 2 or len(required) >= 2:
        reason = f"strict_term: matched_high_count={matched_high_count}, required_target_terms={len(required)}"
        return "strict_term", reason, features

    if matched_high_count >= 1 and features["legal_keyword_count"] >= 1:
        reason = "strict_term: high-priority term in legal/test/approval context"
        return "strict_term", reason, features

    if features["simple_short_text"]:
        reason = "lightweight: short simple text without high-priority term or strong structure"
        return "lightweight", reason, features

    reason = "natural_legal: default for ordinary regulation prose"
    return "natural_legal", reason, features


def classify_sample(
    source_text: str,
    matched_terms: list[dict[str, Any]],
    retry_needed: bool = False,
    source_char_count: int | None = None,
    segment_type: str | None = None,
    section_no: Any = None,
) -> str:
    mode, _, _ = route_prompt_mode(
        source_text=source_text,
        matched_terms=matched_terms,
        source_char_count=source_char_count,
        segment_type=segment_type,
        section_no=section_no,
        retry_needed=retry_needed,
    )
    return mode


def build_prompt_text(
    source_text: str,
    source_lang: str,
    target_lang: str = "zh",
    experiment_group: str = "graded_prompt",
    prompt_mode: str = "natural_legal",
    required_targets: list[str] | None = None,
    review_terms: list[dict[str, Any]] | None = None,
    soft_terms: list[dict[str, Any]] | None = None,
) -> str:
    if experiment_group == "no_term_baseline" or prompt_mode == "general_no_terms":
        return no_term_general_template(source_text, source_lang, target_lang)
    if experiment_group == "term_baseline" or prompt_mode == "general_with_terms":
        return term_general_template(source_text, source_lang, target_lang, required_targets, review_terms, soft_terms)
    builders = {
        "lightweight": lightweight_template,
        "structure": structure_template,
        "strict_term": strict_term_template,
        "natural_legal": natural_legal_template,
    }
    builder = builders.get(prompt_mode, natural_legal_template)
    return builder(source_text, source_lang, target_lang, required_targets, review_terms, soft_terms)


def build_messages(
    source_text: str,
    source_lang: str,
    target_lang: str = "zh",
    matched_terms: list[dict[str, Any]] | None = None,
    prompt_mode: str = "natural_legal",
    current_translation: str = "",
    failed_terms: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    matched_terms = matched_terms or []
    failed_terms = failed_terms or []
    system = (
        "You are a professional automotive regulation translator. "
        "Translate faithfully, keep legal tone, preserve numbers, units, symbols, "
        "regulation references, clause numbers, and table-like structure. "
        "Return only the translation, with no explanations."
    )
    if prompt_mode == RETRY_PROMPT_MODE:
        user = retry_repair_template(source_text, current_translation, failed_terms, source_lang, target_lang)
    else:
        user = build_prompt_text(
            source_text=source_text,
            source_lang=source_lang,
            target_lang=target_lang,
            experiment_group="graded_prompt",
            prompt_mode=prompt_mode,
            required_targets=required_target_terms(matched_terms),
            review_terms=collect_review_terms(matched_terms),
            soft_terms=collect_soft_terms(matched_terms),
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
