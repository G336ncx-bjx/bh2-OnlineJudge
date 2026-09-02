"""统一响应结构 helper。

所有 API 响应格式：{"code": <http状态码>, "msg": "...", "data": ...}
"""
from typing import Any, Optional

from fastapi.responses import JSONResponse


def ok(data: Any = None, msg: str = "success", status_code: int = 200) -> JSONResponse:
    """成功响应。"""
    return JSONResponse(
        status_code=status_code,
        content={"code": status_code, "msg": msg, "data": data},
    )


def err(status_code: int, msg: str, data: Any = None) -> JSONResponse:
    """错误响应，code 与 HTTP 状态码保持一致。"""
    return JSONResponse(
        status_code=status_code,
        content={"code": status_code, "msg": msg, "data": data},
    )
