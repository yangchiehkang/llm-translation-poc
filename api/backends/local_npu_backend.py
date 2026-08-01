# local_npu 后端：与 dashscope 后端同签名，指向本地 OpenAI 兼容推理服务（vLLM / MindIE 等）。
# 本期不做模型选型、显存规划、卡号分配——这些不是本期内容。
# 未配置 LOCAL_NPU_BASE_URL 时明确报错，不静默假装成功。

from __future__ import annotations

import threading
from typing import Any

from api.config import CONFIG
from api.backends.base import (
    TranslationBackend, TranslationTruncated, build_translation_messages, dynamic_max_tokens,
)


def _require_config() -> None:
    if not CONFIG.LOCAL_NPU_BASE_URL or not CONFIG.LOCAL_NPU_MODEL:
        raise RuntimeError(
            "local_npu 后端未配置：请设置 LOCAL_NPU_BASE_URL 和 LOCAL_NPU_MODEL "
            "（指向本期已在跑的本地 OpenAI 兼容推理服务）"
        )


# 本次调用的 usage（prompt/completion tokens）。接口响应体按合同不含 token 数，
# 但延迟表与容量规划都要它（2026-07-30 重测 40004 延迟时补）：用 thread-local
# 旁路带出，不改后端签名、不改响应契约。与 dashscope 后端捕获 finish_reason
# 用的是同一套手法。
_LAST = threading.local()


def last_usage() -> dict[str, Any]:
    """取本线程上一次 chat_completion 的 usage；没有则空 dict。"""
    return getattr(_LAST, "usage", None) or {}


def chat_completion(
    messages: list[dict[str, str]], *, max_tokens: int, temperature: float
) -> tuple[str, str | None]:
    # 单次 OpenAI 兼容 chat 调用。翻译与语种识别共用这一条 httpx 路径，不另写一套。
    # 返回 (content, finish_reason)；是否按 finish_reason 处理截断由调用方决定。
    _require_config()
    import httpx

    payload = {
        "model": CONFIG.LOCAL_NPU_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {CONFIG.LOCAL_NPU_API_KEY}"}
    url = CONFIG.LOCAL_NPU_BASE_URL.rstrip("/") + "/chat/completions"
    with httpx.Client(timeout=CONFIG.TIMEOUT) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    choice = data["choices"][0]
    content = choice.get("message", {}).get("content") or ""
    _LAST.usage = data.get("usage") or {}
    return content, choice.get("finish_reason")


class LocalNpuBackend(TranslationBackend):
    name = "local_npu"

    def translate(self, text: str, src_lang: str, tgt_lang: str, terms: list[dict[str, Any]]) -> str:
        messages = build_translation_messages(text, src_lang, tgt_lang, terms)
        if CONFIG.DYNAMIC_MAX_TOKENS:
            max_tokens = dynamic_max_tokens(
                len(text), CONFIG.MAX_TOKENS, CONFIG.MODEL_MAX_OUTPUT_TOKENS, CONFIG.OUTPUT_TOKENS_RATIO,
            )
        else:
            max_tokens = CONFIG.MAX_TOKENS
        content, finish_reason = chat_completion(
            messages, max_tokens=max_tokens, temperature=CONFIG.TEMPERATURE,
        )
        # 检查截断：finish_reason == 'length' 说明触顶被截，绝不返回半截译文。
        if finish_reason == "length":
            raise TranslationTruncated(
                f"译文超长被截断（finish_reason=length, max_tokens={max_tokens}）：请缩短输入文本"
            )
        return content.strip()

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float) -> str:
        content, _finish = chat_completion(messages, max_tokens=max_tokens, temperature=temperature)
        return content

    def info(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "model": CONFIG.LOCAL_NPU_MODEL or None,
            "base_url": CONFIG.LOCAL_NPU_BASE_URL or None,
            "configured": bool(CONFIG.LOCAL_NPU_BASE_URL and CONFIG.LOCAL_NPU_MODEL),
        }

    def reachable(self, timeout: float = 2.0) -> tuple[bool, str]:
        """GET {base_url}/models —— 极轻，不产生推理，不占卡。只探测，绝不抛异常。"""
        if not CONFIG.LOCAL_NPU_BASE_URL or not CONFIG.LOCAL_NPU_MODEL:
            return (False, "LOCAL_NPU_BASE_URL / LOCAL_NPU_MODEL 未配置")
        url = CONFIG.LOCAL_NPU_BASE_URL.rstrip("/") + "/models"
        try:
            import httpx
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url)
            if resp.status_code != 200:
                return (False, f"{url} 返回 HTTP {resp.status_code}")
            served = {m.get("id") for m in (resp.json().get("data") or [])}
            if CONFIG.LOCAL_NPU_MODEL not in served:
                # 端口活着但换了模型——这比连不上更隐蔽，必须报出来。
                return (False, f"端点在线但不提供 {CONFIG.LOCAL_NPU_MODEL}；实际提供 {sorted(served)}")
            return (True, "ok")
        except Exception as exc:                                   # noqa: BLE001
            return (False, f"{type(exc).__name__}: {exc}")
