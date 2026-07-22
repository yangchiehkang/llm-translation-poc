# 日志：控制台 + 文件。字段含 request_id / 接口 / translateType / languageType /
# 原文长度 / 命中术语数 / 耗时 / 结果状态。原文只记前 200 字符（法规原文可能敏感）。

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from api.config import CONFIG

_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    os.makedirs(CONFIG.LOG_DIR, exist_ok=True)
    level = getattr(logging, CONFIG.LOG_LEVEL.upper(), logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)

    file_handler = RotatingFileHandler(
        os.path.join(CONFIG.LOG_DIR, "api.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    _CONFIGURED = True


def clip_source(text: str) -> str:
    n = CONFIG.SOURCE_LOG_CHARS
    text = (text or "").replace("\n", " ")
    return text[:n] + ("…" if len(text) > n else "")
