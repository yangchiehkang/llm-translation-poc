# 共享工具：读取术语库、匹配源文术语，并判断 hard required terms。
# TCR 检查、Prompt 路由和服务器翻译都会复用这些术语逻辑。

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from scripts.common.io_utils import read_csv, parse_json_list
from scripts.common.lang import normalize_lang


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def split_aliases(value: str | None) -> list[str]:
    if not value:
        return []
    # Keep slash-bearing aliases such as "7/16 inch" intact.
    parts = re.split(r"[|;,\n]+", value)
    return [p.strip() for p in parts if p.strip()]


def load_termbase(
    path: str,
    source_lang: str | None = None,
    target_lang: str | None = "zh",
    active_status: str | Iterable[str] | None = "active",
) -> list[dict[str, Any]]:
    source_lang = normalize_lang(source_lang)
    target_lang = normalize_lang(target_lang)
    allowed_statuses: set[str] | None
    if active_status is None:
        allowed_statuses = None
    elif isinstance(active_status, str):
        allowed_statuses = {active_status.strip().lower()}
    else:
        allowed_statuses = {str(x).strip().lower() for x in active_status if str(x).strip()}
    rows = []
    for row in read_csv(path):
        src = normalize_lang(row.get("source_lang") or row.get("src_lang"))
        tgt = normalize_lang(row.get("target_lang") or row.get("tgt_lang"))
        status = (row.get("status") or row.get("effective_status") or "active").strip().lower()
        if source_lang and src != source_lang:
            continue
        if target_lang and tgt != target_lang:
            continue
        if allowed_statuses is not None and status not in allowed_statuses:
            continue
        source_term = (row.get("source_term") or "").strip()
        target_term = (row.get("target_term") or "").strip()
        if not source_term or not target_term:
            continue
        out = dict(row)
        out["source_lang"] = src
        out["target_lang"] = tgt
        out["source_term"] = source_term
        out["target_term"] = target_term
        out["priority"] = (row.get("priority") or "").strip().lower()
        out["status"] = status
        out["aliases"] = split_aliases(row.get("alias") or row.get("aliases"))
        rows.append(out)
    rows.sort(key=lambda r: len(r["source_term"]), reverse=True)
    return rows


def _term_spans(text: str, term: str, case_sensitive: bool = False) -> list[tuple[int, int]]:
    # 返回 term 在 text 中的全部匹配区间，供最长优先的区间占用抑制使用。
    if not text or not term:
        return []
    flags = 0 if case_sensitive else re.IGNORECASE
    escaped = re.escape(term)
    if term[0].isalnum() and term[-1].isalnum():
        pattern = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
    else:
        pattern = escaped
    return [(m.start(), m.end()) for m in re.finditer(pattern, text, flags=flags)]


def _contains_term(text: str, term: str, case_sensitive: bool = False) -> bool:
    return bool(_term_spans(text, term, case_sensitive=case_sensitive))


def match_terms(text: str, terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按「实际占住的文本区间」做最长优先抑制，返回该文本适用的术语。

    占用做在 span 上而不是 term 上：术语可以经 alias 命中，而 alias 长度与
    source_term 长度无关（REESS 只有 5 字符，其 alias "Rechargeable Electrical
    Energy Storage System" 有 44 字符）。若按 source_term 长度排序，长 alias
    占住的区间不会被任何"更短"的术语先占，长短两条术语会双双进 required。

    同一区间上 source_term 直接命中优先于 alias 命中：文本写 dummy 时只保留
    dummy 本身，不再让 manikin 靠 alias 把同一段文本再要求一次。
    """
    # 1) 收集全部候选：(区间长度, 是否 alias, start, end, 术语序号, 命中文本, 命中来源)
    candidates: list[tuple[int, int, int, int, int, str, str]] = []
    for idx, term in enumerate(terms):
        case_sensitive = _truthy(term.get("case_sensitive"))
        source_term = str(term.get("source_term") or "")
        for start, end in _term_spans(text, source_term, case_sensitive=case_sensitive):
            candidates.append((end - start, 0, start, end, idx, source_term, "source_term"))
        for alias in term.get("aliases") or []:
            for start, end in _term_spans(text, alias, case_sensitive=case_sensitive):
                candidates.append((end - start, 1, start, end, idx, alias, "alias"))
    # 2) 区间长度降序 -> source_term 优先于 alias -> 出现位置，保证结果确定
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

    occupied: list[tuple[int, int]] = []
    chosen: dict[int, tuple[str, str]] = {}
    for _len, _is_alias, start, end, idx, matched_text, matched_by in candidates:
        if any(o_start <= start and end <= o_end for o_start, o_end in occupied):
            continue
        occupied.append((start, end))
        chosen.setdefault(idx, (matched_text, matched_by))

    matched = []
    seen = set()
    # 输出顺序保持 source_term 长度降序，与修复前一致，避免下游依赖顺序时出现漂移。
    for idx in sorted(chosen, key=lambda i: len(str(terms[i].get("source_term") or "")), reverse=True):
        term = terms[idx]
        source_term = term.get("source_term", "")
        matched_text, matched_by = chosen[idx]
        key = term.get("term_id") or (term.get("source_lang"), source_term, term.get("target_term"))
        if key in seen:
            continue
        seen.add(key)
        matched.append({
            "term_id": term.get("term_id", ""),
            "source_lang": term.get("source_lang", ""),
            "target_lang": term.get("target_lang", "zh"),
            "source_term": source_term,
            "target_term": term.get("target_term", ""),
            "domain": term.get("domain", ""),
            "priority": term.get("priority", ""),
            "alias": term.get("alias", ""),
            "note": term.get("note", ""),
            "status": term.get("status", ""),
            "tcr_scope": term.get("tcr_scope", ""),
            "is_core_high": term.get("is_core_high", ""),
            "aliases": term.get("aliases", []),
            "matched_text": matched_text,
            "matched_by": matched_by,
        })
    return matched


def is_hard_required(term: dict[str, Any]) -> bool:
    priority = str(term.get("priority") or "").lower()
    status = str(term.get("status") or "active").lower()
    return priority == "high" and status == "active"


def is_review_term(term: dict[str, Any]) -> bool:
    priority = str(term.get("priority") or "").lower()
    status = str(term.get("status") or "active").lower()
    return status == "review" or (status == "active" and priority == "medium")


def is_soft_term(term: dict[str, Any]) -> bool:
    priority = str(term.get("priority") or "").lower()
    status = str(term.get("status") or "active").lower()
    return status == "active" and priority == "low"


def hard_required_terms(matched_terms: list[dict[str, Any]], scope: str = "hard") -> list[dict[str, Any]]:
    if scope == "all":
        return matched_terms
    return [term for term in matched_terms if is_hard_required(term)]


def review_terms(matched_terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [term for term in matched_terms if is_review_term(term)]


def soft_terms(matched_terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [term for term in matched_terms if is_soft_term(term)]


def get_matched_terms(row: dict[str, Any]) -> list[dict[str, Any]]:
    value = row.get("matched_terms")
    parsed = parse_json_list(value)
    return [x for x in parsed if isinstance(x, dict)]


def required_target_terms(matched_terms: list[dict[str, Any]], scope: str = "hard") -> list[str]:
    out = []
    seen = set()
    for term in hard_required_terms(matched_terms, scope=scope):
        target = str(term.get("target_term") or "").strip()
        if target and target not in seen:
            seen.add(target)
            out.append(target)
    return out


def count_core_high(matched_terms: list[dict[str, Any]]) -> int:
    return sum(1 for term in matched_terms if is_hard_required(term))


def target_present(translation: str, term: dict[str, Any], allow_alias: bool = False) -> bool:
    target = str(term.get("target_term") or "").strip()
    if target and target in translation:
        return True
    if allow_alias:
        for alias in term.get("aliases") or []:
            if alias and alias in translation:
                return True
    return False
