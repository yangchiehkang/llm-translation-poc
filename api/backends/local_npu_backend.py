# local_npu 后端：与 dashscope 后端同签名，指向本地 OpenAI 兼容推理服务（vLLM / MindIE 等）。
# 本期不做模型选型、显存规划、卡号分配——这些不是本期内容。
# 未配置 LOCAL_NPU_BASE_URL 时明确报错，不静默假装成功。

from __future__ import annotations

from typing import Any

from api.config import CONFIG
from api.backends.base import (
    TranslationBackend, TranslationTruncated, build_translation_messages, dynamic_max_tokens,
)


class LocalNpuBackend(TranslationBackend):
    name = "local_npu"

    def translate(self, text: str, src_lang: str, tgt_lang: str, terms: list[dict[str, Any]]) -> str:
        if not CONFIG.LOCAL_NPU_BASE_URL or not CONFIG.LOCAL_NPU_MODEL:
            raise RuntimeError(
                "local_npu 后端未配置：请设置 LOCAL_NPU_BASE_URL 和 LOCAL_NPU_MODEL "
                "（指向本期已在跑的本地 OpenAI 兼容推理服务）"
            )
        messages = build_translation_messages(text, src_lang, tgt_lang, terms)
        if CONFIG.DYNAMIC_MAX_TOKENS:
            max_tokens = dynamic_max_tokens(
                len(text), CONFIG.MAX_TOKENS, CONFIG.MODEL_MAX_OUTPUT_TOKENS, CONFIG.OUTPUT_TOKENS_RATIO,
            )
        else:
            max_tokens = CONFIG.MAX_TOKENS
        # 用 openai 兼容 HTTP 调用，避免在本层引入任何模型加载/显存逻辑。
        import httpx

        payload = {
            "model": CONFIG.LOCAL_NPU_MODEL,
            "messages": messages,
            "temperature": CONFIG.TEMPERATURE,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {CONFIG.LOCAL_NPU_API_KEY}"}
        url = CONFIG.LOCAL_NPU_BASE_URL.rstrip("/") + "/chat/completions"
        with httpx.Client(timeout=CONFIG.TIMEOUT) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise TranslationTruncated(
                f"译文超长被截断（finish_reason=length, max_tokens={max_tokens}）：请缩短输入文本"
            )
        return choice["message"]["content"].strip()

    def info(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "model": CONFIG.LOCAL_NPU_MODEL or None,
            "base_url": CONFIG.LOCAL_NPU_BASE_URL or None,
            "configured": bool(CONFIG.LOCAL_NPU_BASE_URL and CONFIG.LOCAL_NPU_MODEL),
        }
