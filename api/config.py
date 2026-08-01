# 配置层：所有可调项集中在这里，全部走环境变量 / .env，代码里不写任何密钥。
# .env 通过 python-dotenv 加载；systemd 用 EnvironmentFile 注入，二者取值一致。

from __future__ import annotations

import os
from pathlib import Path

# api/ 的上一级就是项目根，scripts.common 依赖它在 sys.path 上。
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    # .env 是唯一权威配置源，覆盖进程里可能存在的同名变量。
    # 关键原因：登录 shell 的 .bashrc 里有占位符 export DASHSCOPE_API_KEY="你的..."，
    # 若不覆盖，任何在登录 shell 里起的进程都会拿到占位符而非 .env 的真实密钥。
    # 对 systemd 服务无副作用：EnvironmentFile 就是同一个 .env，值完全一致。
    env_path = PROJECT_ROOT / os.getenv("API_ENV_FILE", ".env")
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=True)
    except Exception:
        # 没装 python-dotenv 也不致命：手动解析并覆盖。
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


_load_dotenv()


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value is not None and value != "" else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").strip().lower() in {"1", "true", "yes", "y", "on"}


class Config:
    # ---- 后端开关：本期只做契约层，后端差异对上层不可见 ----
    BACKEND: str = _env("BACKEND", "dashscope").strip().lower()  # dashscope | local_npu

    # ---- 网络：优先 IPv4，规避本机 IPv6 到 dashscope 不通导致的 ~63s SYN 超时 ----
    PREFER_IPV4: bool = _env_bool("PREFER_IPV4", True)

    # ---- 鉴权 ----
    # 支持多个 token（国创一个、自测一个），逗号分隔；缺失或不匹配 -> code:401
    API_TOKENS: list[str] = [t.strip() for t in _env("API_TOKENS", "").split(",") if t.strip()]

    # ---- 路由路径（做成配置项）----
    LAW_PATH: str = _env("LAW_PATH", "/openApi/translate/law")
    TERMINOLOGY_LIST_PATH: str = _env("TERMINOLOGY_LIST_PATH", "/openApi/terminology/list")

    # ---- 术语库 ----
    TERMBASE_PATH: str = str(PROJECT_ROOT / _env("TERMBASE_PATH", "termbase/auto_regulation_terms_v1.csv"))
    # terminology/list 默认返回数组；开关可切回单对象（文档示例是单对象但接口名叫 list）
    TERMINOLOGY_LIST_AS_OBJECT: bool = _env_bool("TERMINOLOGY_LIST_AS_OBJECT", False)

    # ---- 长文本上限（保守值，拿去和国创承诺）----
    # 推导见 README_DEPLOY.md：qwen-max 上下文减去输出与 prompt 开销后反推的保守字符数。
    MAX_TEXT_CHARS: int = _env_int("MAX_TEXT_CHARS", 8000)

    # ---- dashscope 后端参数（复用现有 call_dashscope_generation 的入参）----
    MODEL_NAME: str = _env("MODEL_NAME", "qwen-max")
    TEMPERATURE: float = _env_float("TEMPERATURE", 0.2)
    # 输出上限：英译中一段长文本约需数千 token，2048 会被静默截断，故提高到 4096 作下限。
    MAX_TOKENS: int = _env_int("MAX_TOKENS", 4096)
    # 按输入长度动态计算输出上限，夹在 [MAX_TOKENS, MODEL_MAX_OUTPUT_TOKENS] 之间。
    DYNAMIC_MAX_TOKENS: bool = _env_bool("DYNAMIC_MAX_TOKENS", True)
    MODEL_MAX_OUTPUT_TOKENS: int = _env_int("MODEL_MAX_OUTPUT_TOKENS", 8192)  # 双后端共用的输出上限；当前后端 40018 上下文 32768
    OUTPUT_TOKENS_RATIO: float = _env_float("OUTPUT_TOKENS_RATIO", 1.2)  # 输出token/输入字符 保守系数
    TIMEOUT: int = _env_int("TIMEOUT", 120)
    RETRIES: int = _env_int("RETRIES", 3)

    # ---- local_npu 后端（本期不做模型选型/卡号分配；仅保留同签名后端占位，指向本地 OpenAI 兼容服务）----
    LOCAL_NPU_BASE_URL: str = _env("LOCAL_NPU_BASE_URL", "")
    LOCAL_NPU_MODEL: str = _env("LOCAL_NPU_MODEL", "")
    LOCAL_NPU_API_KEY: str = _env("LOCAL_NPU_API_KEY", "EMPTY")

    # ---- 服务监听 ----
    HOST: str = _env("HOST", "0.0.0.0")
    # 端口的真正消费者是 api/deploy/run.sh（systemd ExecStart 调它），本字段目前
    # 无人读取，仅作配置回显。**不设写死默认值**：曾默认 8188，而 220 已切 4188、
    # 125 用 4188，任何写死值都会让读代码的人得出错误结论。0 表示未配置。
    PORT: int = _env_int("PORT", 0)

    # ---- 日志 ----
    LOG_DIR: str = _env("LOG_DIR", str(PROJECT_ROOT / "logs"))
    LOG_LEVEL: str = _env("LOG_LEVEL", "INFO")
    SOURCE_LOG_CHARS: int = _env_int("SOURCE_LOG_CHARS", 200)  # 原文只记前 200 字符


CONFIG = Config()
