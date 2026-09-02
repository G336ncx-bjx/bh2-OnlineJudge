"""依赖注入：Session 认证、权限校验、提交频率限制。"""
import time
from typing import Optional

from fastapi import Request

from . import storage

# 记录每个用户最近提交时间，用于频率限制
_rate_records: dict[str, list[float]] = {}


def get_current_user(request: Request) -> Optional[dict]:
    """从 session 中读取当前登录用户，返回用户 dict 或 None。

    会话采用「无状态签名 cookie + 服务端版本号」双重校验：
    cookie 里的 session_version(sv) 必须与用户数据里的 session_version 一致，
    否则视为会话已失效（logout 会递增版本号使所有旧 cookie 失效）。
    """
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    users = storage.get_users()
    user = users.get(user_id)
    if user is None:
        return None
    # 校验会话版本号，防止 logout 后的旧 cookie 继续生效
    cookie_sv = request.session.get("sv")
    stored_sv = user.get("session_version", 0)
    if cookie_sv is None or cookie_sv != stored_sv:
        return None
    return user


def require_login(request: Request) -> Optional[dict]:
    """要求登录。未登录返回 None，调用方据此返回 401。"""
    return get_current_user(request)


def is_admin(user: Optional[dict]) -> bool:
    return bool(user and user.get("role") == "admin")


def check_rate_limit(user_id: str) -> bool:
    """频率限制：1 分钟内超过 3 次提交返回 False。"""
    now = time.time()
    records = _rate_records.setdefault(user_id, [])
    # 清理 1 分钟前的记录
    records[:] = [t for t in records if now - t < 60]
    if len(records) >= 3:
        return False
    records.append(now)
    return True


def reset_rate_limits() -> None:
    _rate_records.clear()
