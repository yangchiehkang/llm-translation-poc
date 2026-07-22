# 后端分发：backend 配置开关（dashscope | local_npu）选一个实现，
# 两个后端封装成同一个函数签名 translate(text, src_lang, tgt_lang, terms) -> str。
# 契约层完全不感知后端差异。

from __future__ import annotations

from typing import Any

from api.config import CONFIG


def get_backend():
    backend = CONFIG.BACKEND
    if backend == "dashscope":
        from api.backends.dashscope_backend import DashScopeBackend
        return DashScopeBackend()
    if backend == "local_npu":
        from api.backends.local_npu_backend import LocalNpuBackend
        return LocalNpuBackend()
    raise RuntimeError(f"unknown BACKEND={backend!r}, expected 'dashscope' or 'local_npu'")


def translate(text: str, src_lang: str, tgt_lang: str, terms: list[dict[str, Any]]) -> str:
    # 统一入口。上层只调这个，不关心底层是云 API 还是本地 NPU。
    return get_backend().translate(text, src_lang, tgt_lang, terms)
