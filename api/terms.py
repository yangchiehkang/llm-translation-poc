# 术语层：把契约里的 originalTerminology/translateTerminology 映射到内部 source_term/target_term，
# 一律按 priority=high 硬约束处理；请求内优先、本地 CSV 补充、冲突以请求方为准（记 INFO）。
# 全程复用 scripts.common.termbase 的现有函数，不另写匹配/校验逻辑。

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from api.config import CONFIG
from scripts.common.termbase import load_termbase, match_terms, target_present, hard_required_terms

logger = logging.getLogger("api.terms")


@lru_cache(maxsize=32)
def _local_termbase(source_lang: str, target_lang: str) -> tuple[dict[str, Any], ...]:
    # 本地 CSV 术语库按语向缓存（进程内），避免每请求重复读 2000+ 行。
    rows = load_termbase(CONFIG.TERMBASE_PATH, source_lang=source_lang, target_lang=target_lang)
    return tuple(rows)


def _request_term(source_term: str, target_term: str, source_lang: str, target_lang: str) -> dict[str, Any]:
    # 请求传入的术语显式塑形成 load_termbase 的输出结构，并强制 priority=high / status=active，
    # 这样才能走现有 required_target_terms 硬约束注入路径。
    return {
        "term_id": f"REQ::{source_term}",
        "source_lang": source_lang,
        "target_lang": target_lang,
        "source_term": source_term.strip(),
        "target_term": target_term.strip(),
        "domain": "request",
        "priority": "high",
        "alias": "",
        "note": "request-supplied",
        "status": "active",
        "aliases": [],
    }


def build_termbase(
    request_terms: list[dict[str, str]],
    source_lang: str,
    target_lang: str,
    request_id: str,
) -> list[dict[str, Any]]:
    # 返回合并后的术语库（请求优先 + 本地补充），供 match_terms 匹配。
    merged: list[dict[str, Any]] = []
    request_targets: dict[str, str] = {}  # 归一化 source_term -> 请求方指定译法

    for item in request_terms:
        src = str(item.get("originalTerminology") or "").strip()
        tgt = str(item.get("translateTerminology") or "").strip()
        if not src or not tgt:
            continue
        key = src.lower()
        request_targets[key] = tgt
        merged.append(_request_term(src, tgt, source_lang, target_lang))

    for row in _local_termbase(source_lang, target_lang):
        key = str(row.get("source_term") or "").strip().lower()
        if key in request_targets:
            # 冲突：请求内术语优先，本地 CSV 让位。记 INFO（含 request_id 和两边译法）。
            if request_targets[key] != str(row.get("target_term") or "").strip():
                logger.info(
                    "term conflict request_id=%s source_term=%r request_target=%r local_target=%r -> use request",
                    request_id, row.get("source_term"), request_targets[key], row.get("target_term"),
                )
            continue
        merged.append(dict(row))

    # 长术语优先，保持 match_terms 的既有匹配语义。
    merged.sort(key=lambda r: len(str(r.get("source_term") or "")), reverse=True)
    return merged


def match(text: str, merged_terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # 直接复用现有 match_terms：大小写不敏感、词边界、长术语优先、已去重。
    return match_terms(text, merged_terms)


def verify_targets(translation: str, matched_terms: list[dict[str, Any]], request_id: str) -> list[str]:
    # 译后用 target_present() 校验硬约束术语是否出现；未命中记 WARNING，不做强制替换。
    missing: list[str] = []
    for term in hard_required_terms(matched_terms):
        if not target_present(translation, term):
            missing.append(str(term.get("target_term") or ""))
    if missing:
        logger.warning(
            "term target(s) not present in translation request_id=%s missing=%s",
            request_id, missing,
        )
    return missing
