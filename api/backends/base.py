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

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float) -> str:
        # 单次原语生成，供翻译以外的用途（如语种识别）复用当前后端，不直连某个具体实现。
        # 各后端各自实现；返回模型原始文本，不做截断判定。
        raise NotImplementedError

    def classify(self, text: str, labels: list[str]) -> str:
        # 后端无关的受约束分类：只在 labels 里选一个，返回模型原始输出（调用方负责解析/校验）。
        # 这样语种识别在 dashscope / local_npu 下都能用当前后端完成，不依赖 LOCAL_NPU_* 是否配置。
        label_str = "、".join(labels)
        system = (
            f"你是一个分类器。从下列候选标签中选出最匹配输入文本的一个，"
            f"只输出该标签本身（原样、不加任何其他字符）：{label_str}。"
            "不要输出解释、标点或空格。"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]
        return self.complete(messages, max_tokens=8, temperature=0.0)

    def info(self) -> dict[str, Any]:
        return {"backend": self.name}
