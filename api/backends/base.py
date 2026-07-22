# 后端统一签名。两个后端都复用 scripts.common.prompting.build_messages 构造消息，
# 差异只在"消息发给谁"。翻译逻辑本身一行不改。

from __future__ import annotations

import math
from typing import Any

from scripts.common.prompting import build_messages, classify_sample


class TranslationTruncated(RuntimeError):
    # 译文被 max_tokens 截断（finish_reason == 'length'）。绝不静默返回半截译文。
    pass


def dynamic_max_tokens(input_chars: int, floor: int, ceil: int, ratio: float) -> int:
    # 按输入长度反推输出上限：X->中文时输出 token 数不会远超输入字符数，
    # 乘以保守系数并夹在 [floor, ceil] 之间；ceil 为模型输出硬上限。
    need = int(math.ceil(input_chars * ratio)) + 64
    return max(floor, min(ceil, need))


def build_translation_messages(
    text: str, src_lang: str, tgt_lang: str, terms: list[dict[str, Any]]
) -> list[dict[str, str]]:
    # 与现有 CLI 管线一致：按匹配术语自动路由 prompt_mode，再复用 build_messages。
    prompt_mode = classify_sample(text, terms)
    return build_messages(text, src_lang, tgt_lang, terms, prompt_mode)


class TranslationBackend:
    name: str = "base"

    def translate(self, text: str, src_lang: str, tgt_lang: str, terms: list[dict[str, Any]]) -> str:
        raise NotImplementedError

    def info(self) -> dict[str, Any]:
        return {"backend": self.name}
