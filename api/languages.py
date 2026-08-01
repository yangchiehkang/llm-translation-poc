# languageType 显式映射表。不静默 fallback：未知取值由调用方转成 code:422 并列出支持枚举。
# 只覆盖现有术语库真实支持的 X->中文 方向（termbase 全部 target_lang=zh）。

from __future__ import annotations

# 契约里的 languageType -> (内部 source_lang, 内部 target_lang)
LANGUAGE_TYPE_MAP: dict[str, tuple[str, str]] = {
    "EN-CN": ("en", "zh"),
    "DE-CN": ("de", "zh"),
    "FR-CN": ("fr", "zh"),
    "ES-CN": ("es", "zh"),
    "RU-CN": ("ru", "zh"),
    "AR-CN": ("ar", "zh"),
    "TH-CN": ("th", "zh"),
}

SUPPORTED_LANGUAGE_TYPES: list[str] = list(LANGUAGE_TYPE_MAP.keys())


def _normalize(language_type: object) -> str:
    # 契约里 languageType 是字符串，但调用方可能传来数字/数组/对象/布尔。
    # 先无条件转字符串再归一：直接 .strip() 会抛 AttributeError，被全局兜底转成
    # code:500 且把 "'int' object has no attribute 'strip'" 原样吐给调用方——
    # 既与"不支持的枚举值返回 code:422"的对外承诺不符，也泄露内部实现。
    if language_type is None:
        return ""
    return str(language_type).strip().upper()


def resolve_language_type(language_type: object) -> tuple[str, str] | None:
    # 大小写与空白归一，命中返回 (src, tgt)，未命中返回 None（由调用方报 422）。
    key = _normalize(language_type)
    if not key:
        return None
    return LANGUAGE_TYPE_MAP.get(key)


def canonical_language_type(language_type: object) -> str | None:
    # 归一化回枚举原形（如 " en-cn " -> "EN-CN"），供 detectedLanguageType 回显用：
    # 回显必须落在对外公布的枚举里，不能把调用方的大小写/空格原样退回去。
    key = _normalize(language_type)
    return key if key in LANGUAGE_TYPE_MAP else None
