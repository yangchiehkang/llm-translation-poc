# 共享工具：统一语言代码、语言名称和从文件名推断语种的逻辑。
# 避免各脚本重复维护 en/de/fr 等语言映射。

from __future__ import annotations

import re
from pathlib import Path

LANG_NAME = {
    "ar": "Arabic",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "id": "Indonesian",
    "it": "Italian",
    "ms": "Malay",
    "nl": "Dutch",
    "no": "Norwegian",
    "pt": "Portuguese",
    "ru": "Russian",
    "sv": "Swedish",
    "th": "Thai",
    "vi": "Vietnamese",
    "zh": "Chinese",
}

ALIASES = {name.lower(): code for code, name in LANG_NAME.items()}
ALIASES.update({"zh-cn": "zh", "zh_cn": "zh", "cn": "zh", "chinese": "zh"})


def normalize_lang(value: str | None) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    if text in LANG_NAME:
        return text
    return ALIASES.get(text, text)


def lang_name(code: str | None) -> str:
    code = normalize_lang(code)
    return LANG_NAME.get(code, code or "Unknown")


def infer_lang_from_path(path: str | Path) -> str:
    name = Path(path).name.lower()
    patterns = [
        r"^([a-z]{2})\.jsonl$",
        r"mt_([a-z]{2})\.",
        r"_src_([a-z]{2})",
        r"_([a-z]{2})\.pdf$",
    ]
    for pattern in patterns:
        m = re.search(pattern, name)
        if m:
            code = normalize_lang(m.group(1))
            if code in LANG_NAME:
                return code
    return ""
