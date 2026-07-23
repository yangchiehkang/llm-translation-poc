# 源语种识别（languageType 未显式传入时）。两级：
#   1) Unicode 脚本判定：西里尔/阿拉伯/泰文占比超阈值直接判定 RU/AR/TH。零延迟、确定性、不占 NPU。
#   2) 拉丁字母走 40018：约束模型只在 EN/DE/FR/ES 里选一个，temperature=0、max_tokens 极小。
# 识别不出或不在 7 枚举内 -> 抛 LanguageDetectionError，由上层转 code:422。
# 绝不静默 fallback 到 EN-CN：识别错会让本地术语库按错误 source_lang 过滤、术语静默全丢，比报错难查。

from __future__ import annotations

import logging
import re

from api import backends

logger = logging.getLogger("api.langdetect")


class LanguageDetectionError(RuntimeError):
    # 无法识别源语种（两级都失败）。上层据此返回 code:422，提示显式传 languageType。
    pass


# ---- 第一级：Unicode 脚本占比 ----
_SCRIPT_SAMPLE_CHARS = 500
_SCRIPT_THRESHOLD = 0.20


def _in_cyrillic(o: int) -> bool:
    return 0x0400 <= o <= 0x04FF or 0x0500 <= o <= 0x052F  # Cyrillic + Supplement


def _in_arabic(o: int) -> bool:
    return 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF


def _in_thai(o: int) -> bool:
    return 0x0E00 <= o <= 0x0E7F


def _has_latin(text: str) -> bool:
    # 是否含拉丁字母（含带变音符的德/法/西字母）。用于判断第二级是否有意义。
    return bool(re.search(r"[A-Za-zÀ-ɏ]", text[:_SCRIPT_SAMPLE_CHARS]))


def _script_detect(text: str) -> str | None:
    sample = text[:_SCRIPT_SAMPLE_CHARS]
    letters = cyr = ara = tha = 0
    for ch in sample:
        if not ch.isalpha():
            continue
        letters += 1
        o = ord(ch)
        if _in_cyrillic(o):
            cyr += 1
        elif _in_arabic(o):
            ara += 1
        elif _in_thai(o):
            tha += 1
    if letters == 0:
        return None
    if cyr / letters > _SCRIPT_THRESHOLD:
        return "RU-CN"
    if ara / letters > _SCRIPT_THRESHOLD:
        return "AR-CN"
    if tha / letters > _SCRIPT_THRESHOLD:
        return "TH-CN"
    return None


# ---- 第二级：拉丁字母 -> 当前后端（backends 抽象层，dashscope/local_npu 皆可） ----
_LLM_SAMPLE_CHARS = 300
_LATIN_LABELS = ["EN", "DE", "FR", "ES"]
_LATIN_TYPE = {"EN": "EN-CN", "DE": "DE-CN", "FR": "FR-CN", "ES": "ES-CN"}


def _latin_detect_once(text: str) -> str | None:
    # 通过 backends.classify 走当前后端做受约束分类，不直连 LOCAL_NPU_*。
    label = backends.classify(text[:_LLM_SAMPLE_CHARS], _LATIN_LABELS)
    token = re.sub(r"[^A-Za-z]", "", (label or "")).upper()
    if token in _LATIN_TYPE:
        return _LATIN_TYPE[token]
    # 严格但容一点噪声：取前两个字母再判一次（如模型多吐了 "ENGLISH"）。
    return _LATIN_TYPE.get(token[:2])


def detect_language(text: str, request_id: str = "") -> str:
    # 返回 languageType 枚举（如 "RU-CN"）。识别不出抛 LanguageDetectionError。
    first = _script_detect(text)
    if first:
        logger.info("langdetect request_id=%s tier=script result=%s", request_id, first)
        return first

    # 无 RU/AR/TH 脚本、且完全没有拉丁字母（纯数字/符号/表情）：本就无从识别，
    # 不必让被迫二选一的分类器瞎猜，直接判为不可识别（零 NPU 开销）。
    if not _has_latin(text):
        logger.info("langdetect request_id=%s no script hit and no latin letters -> undetectable", request_id)
        raise LanguageDetectionError("无法识别源语种，请显式传入 languageType")

    last_error: Exception | None = None
    for attempt in (1, 2):  # 拉丁级：解析失败重试一次
        try:
            result = _latin_detect_once(text)
        except Exception as exc:  # 网络/后端异常也算本次失败，重试后仍失败即放弃
            last_error = exc
            result = None
        if result:
            logger.info("langdetect request_id=%s tier=llm attempt=%s result=%s", request_id, attempt, result)
            return result

    logger.warning("langdetect failed request_id=%s last_error=%s", request_id, last_error)
    raise LanguageDetectionError("无法识别源语种，请显式传入 languageType")
