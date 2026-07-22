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


def resolve_language_type(language_type: str | None) -> tuple[str, str] | None:
    # 大小写与空白归一，命中返回 (src, tgt)，未命中返回 None（由调用方报 422）。
    if not language_type:
        return None
    key = language_type.strip().upper()
    return LANGUAGE_TYPE_MAP.get(key)
