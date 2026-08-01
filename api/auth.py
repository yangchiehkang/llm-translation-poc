# 鉴权：Authorization: Bearer {token}，token 从 .env 读，支持多个。
# 缺失或不匹配 -> ApiError(code:401)。业务码，不抛 HTTP 401。

from __future__ import annotations

from fastapi import Request

from api.config import CONFIG
from api.contract import ApiError, CODE_UNAUTHORIZED


def require_bearer(request: Request) -> str:
    if not CONFIG.API_TOKENS:
        # 服务端没配置任何 token：拒绝所有请求，避免裸奔。
        raise ApiError(CODE_UNAUTHORIZED, "服务未配置任何 API token，拒绝访问")
    header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    prefix = "bearer "
    if not header.lower().startswith(prefix):
        raise ApiError(CODE_UNAUTHORIZED, "缺少或格式错误的 Authorization Bearer token")
    token = header[len(prefix):].strip()
    if not token:
        # "Bearer " 后面空着属于格式错误，归第一类 msg——接口文档把两类提示的触发条件
        # 写死了（缺头/漏前缀 vs token 值不对），空 token 报"无效的 API token"会误导自查。
        raise ApiError(CODE_UNAUTHORIZED, "缺少或格式错误的 Authorization Bearer token")
    if token not in CONFIG.API_TOKENS:
        raise ApiError(CODE_UNAUTHORIZED, "无效的 API token")
    return token
