# -*- coding: utf-8 -*-

LANG_CODE_TO_NAME = {
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
}

TARGET_LANG = "zh"
TARGET_LANG_NAME = "Chinese"

RFP_LANGUAGES = {
    "en": {"name": "English", "target": 0.90},
    "es": {"name": "Spanish", "target": 0.85},
    "ru": {"name": "Russian", "target": 0.85},
    "de": {"name": "German", "target": 0.80},
    "fr": {"name": "French", "target": 0.80},
    "th": {"name": "Thai", "target": 0.70},
    "ar": {"name": "Arabic", "target": 0.70},
}

EXTENDED_LANGUAGES = {
    "ms": "Malay",
    "id": "Indonesian",
    "pt": "Portuguese",
    "it": "Italian",
    "nl": "Dutch",
    "no": "Norwegian",
    "sv": "Swedish",
    "vi": "Vietnamese",
}


def get_lang_name(code: str) -> str:
    return LANG_CODE_TO_NAME.get(code, code)


def list_all_lang_codes():
    return list(LANG_CODE_TO_NAME.keys())


def is_rfp_language(code: str) -> bool:
    return code in RFP_LANGUAGES
