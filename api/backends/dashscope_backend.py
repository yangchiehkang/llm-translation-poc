# dashscope 后端：直接复用现有 call_dashscope_generation，不重写任何调用逻辑。
# DASHSCOPE_API_KEY 由环境变量提供（systemd EnvironmentFile / .env），代码里不出现密钥。

from __future__ import annotations

import os
import threading
from typing import Any

from api.config import CONFIG
from api.backends.base import (
    TranslationBackend, TranslationTruncated, build_translation_messages, dynamic_max_tokens,
)
import scripts.common.dashscope_client as dsc
from scripts.common.dashscope_client import call_dashscope_generation


# ---- finish_reason 捕获 ----
# call_dashscope_generation 只返回文本、丢弃了 finish_reason。为在不改动 scripts/、
# 也不复制其重试逻辑的前提下拿到 finish_reason，这里对同模块的 extract_choice_text 做一次
# 永久透明包装：它照常返回文本，同时把 finish_reason 记进 thread-local（并发安全）。
_tl = threading.local()
_orig_extract_choice_text = dsc.extract_choice_text


def _extract_finish_reason(response: Any) -> str | None:
    output = None
    if isinstance(response, dict):
        output = response.get("output")
    if output is None:
        output = getattr(response, "output", None)
    if isinstance(output, dict):
        choices = output.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            fr = choices[0].get("finish_reason")
            if isinstance(fr, str):
                return fr
    return None


def _capturing_extract_choice_text(response: Any) -> str:
    # call_dashscope_generation 内部以模块全局名调用 extract_choice_text，替换后会命中本函数。
    try:
        _tl.finish_reason = _extract_finish_reason(response)
    except Exception:
        _tl.finish_reason = None
    return _orig_extract_choice_text(response)


dsc.extract_choice_text = _capturing_extract_choice_text  # 安装一次，进程内长期生效


def _preflight_key() -> None:
    # 快速失败：密钥缺失 / 含非 ASCII（占位符如 "你的DashScope_API_Key"）时立即报错，
    # 避免 dashscope SDK 内部重试拖到几十秒才抛底层编码异常。
    key = os.getenv("DASHSCOPE_API_KEY", "")
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY 未设置：请在 .env 填入有效的 dashscope 密钥")
    if not key.isascii():
        raise RuntimeError(
            "DASHSCOPE_API_KEY 非法（含非 ASCII 字符，疑似占位符）：请在 .env 填入有效的 dashscope 密钥"
        )


class DashScopeBackend(TranslationBackend):
    name = "dashscope"

    def translate(self, text: str, src_lang: str, tgt_lang: str, terms: list[dict[str, Any]]) -> str:
        _preflight_key()
        messages = build_translation_messages(text, src_lang, tgt_lang, terms)
        if CONFIG.DYNAMIC_MAX_TOKENS:
            max_tokens = dynamic_max_tokens(
                len(text), CONFIG.MAX_TOKENS, CONFIG.MODEL_MAX_OUTPUT_TOKENS, CONFIG.OUTPUT_TOKENS_RATIO,
            )
        else:
            max_tokens = CONFIG.MAX_TOKENS

        _tl.finish_reason = None
        translation, _retries = call_dashscope_generation(
            messages,
            model=CONFIG.MODEL_NAME,
            temperature=CONFIG.TEMPERATURE,
            max_tokens=max_tokens,
            timeout=CONFIG.TIMEOUT,
            max_attempts=CONFIG.RETRIES,
            sleep_seconds=lambda attempt: min(10, 1.5 * attempt),
            retry_log_prefix="[RETRY]",
            failure_message="Qwen-Max call failed after retries",
        )
        # 检查截断：finish_reason == 'length' 说明触顶被截，绝不返回半截译文。
        if getattr(_tl, "finish_reason", None) == "length":
            raise TranslationTruncated(
                f"译文超长被截断（finish_reason=length, max_tokens={max_tokens}）：请缩短输入文本"
            )
        return translation

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float) -> str:
        # 单次 qwen-max 调用，供语种识别等非翻译用途复用。复用现有 call_dashscope_generation，不重写。
        _preflight_key()
        text, _retries = call_dashscope_generation(
            messages,
            model=CONFIG.MODEL_NAME,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=CONFIG.TIMEOUT,
            max_attempts=CONFIG.RETRIES,
            sleep_seconds=lambda attempt: min(10, 1.5 * attempt),
            retry_log_prefix="[RETRY]",
            failure_message="Qwen-Max classify call failed after retries",
        )
        return text

    def info(self) -> dict[str, Any]:
        key = os.getenv("DASHSCOPE_API_KEY", "")
        return {
            "backend": self.name,
            "model": CONFIG.MODEL_NAME,
            "api_key_present": bool(key),
            "api_key_valid": bool(key) and key.isascii(),  # 占位符/非法密钥会是 false
            "max_tokens_floor": CONFIG.MAX_TOKENS,
            "model_max_output_tokens": CONFIG.MODEL_MAX_OUTPUT_TOKENS,
            "dynamic_max_tokens": CONFIG.DYNAMIC_MAX_TOKENS,
        }
