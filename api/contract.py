# 统一契约：所有响应都是 {code, msg, data}，HTTP 状态一律 200，错误体现在 code。
# code 是业务码，不是 HTTP 码：0 成功 / 401 未授权 / 403 无权限 / 404 资源不存在 /
# 422 参数校验失败 / 500 服务端内部错误。data 无数据时为 null。

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


# 业务码常量
CODE_OK = 0
CODE_UNAUTHORIZED = 401
CODE_FORBIDDEN = 403
CODE_NOT_FOUND = 404
CODE_INVALID_PARAM = 422
CODE_INTERNAL = 500


def envelope(code: int, msg: str, data: Any = None) -> dict[str, Any]:
    return {"code": code, "msg": msg, "data": data}


def json_ok(data: Any = None, msg: str = "ok") -> JSONResponse:
    # 业务成功也好、业务错误也好，HTTP 一律 200。
    return JSONResponse(status_code=200, content=envelope(CODE_OK, msg, data))


def json_result(code: int, msg: str, data: Any = None) -> JSONResponse:
    return JSONResponse(status_code=200, content=envelope(code, msg, data))


class ApiError(Exception):
    # 业务异常：在处理器里 raise，由全局异常处理器统一转成 {code,msg,data}，HTTP 200。
    def __init__(self, code: int, msg: str, data: Any = None) -> None:
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.data = data
