"""Step4 用户管理路由：注册、登录、登出、查询、角色、列表、创建管理员。"""
from fastapi import APIRouter, Request

from .. import storage
from ..deps import get_current_user, is_admin
from ..models import UserCreate, LoginRequest, RoleUpdate
from ..schemas import ok, err

import bcrypt

router = APIRouter(prefix="/api", tags=["users"])


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _user_public(user: dict) -> dict:
    """返回不含密码的用户信息。"""
    # attempted_count 惰性计算：旧数据可能没有 attempted_problems 字段，
    # 有则取集合长度（按题去重）
    attempted = user.get("attempted_problems")
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "join_time": user.get("join_time", ""),
        "role": user.get("role", "user"),
        "submit_count": user.get("submit_count", 0),
        "resolve_count": user.get("resolve_count", 0),
        "attempted_count": len(attempted) if isinstance(attempted, list) else 0,
    }


def ensure_initial_admin() -> None:
    """启动时创建初始管理员（admin / admintestpassword）。"""
    users = storage.get_users()
    for u in users.values():
        if u.get("username") == "admin":
            return
    admin_id = storage.new_id()
    users[admin_id] = {
        "user_id": admin_id,
        "username": "admin",
        "password_hash": _hash_password("admintestpassword"),
        "join_time": storage.now_str()[:10],
        "role": "admin",
        "submit_count": 0,
        "resolve_count": 0,
    }
    storage.save_users(users)


# ---------------------------------------------------------------- 认证
@router.post("/auth/login")
async def login(request: Request, body: LoginRequest):
    users = storage.get_users()
    user = None
    for u in users.values():
        if u.get("username") == body.username:
            user = u
            break
    if user is None:
        return err(401, "用户名或密码错误")
    if not _verify_password(body.password, user.get("password_hash", "")):
        return err(401, "用户名或密码错误")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")

    # 写入会话版本号，用于 logout 时吊销旧 cookie（get_current_user 校验 sv 一致性）
    sv = user.get("session_version", 0)
    request.session["user_id"] = user["user_id"]
    request.session["sv"] = sv
    return ok({
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user.get("role", "user"),
    }, "login success")


@router.post("/auth/logout")
async def logout(request: Request):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    # 递增会话版本号，使该用户所有已签发的旧 cookie 立即失效
    users = storage.get_users()
    stored = users.get(user["user_id"])
    if stored is not None:
        stored["session_version"] = stored.get("session_version", 0) + 1
        storage.save_users(users)
    request.session.clear()
    return ok(None, "logout success")


# ---------------------------------------------------------------- 用户
@router.post("/users/")
async def register(request: Request, body: UserCreate):
    username = body.username
    password = body.password

    if not (3 <= len(username) <= 40):
        return err(400, "用户名长度须为 3-40 个字符")
    if len(password) < 6:
        return err(400, "密码长度至少 6 位")

    users = storage.get_users()
    for u in users.values():
        if u.get("username") == username:
            return err(400, "用户名已存在")

    user_id = storage.new_id()
    users[user_id] = {
        "user_id": user_id,
        "username": username,
        "password_hash": _hash_password(password),
        "join_time": storage.now_str()[:10],
        "role": "user",
        "submit_count": 0,
        "resolve_count": 0,
    }
    storage.save_users(users)
    return ok({
        "user_id": user_id,
        "username": username,
        "join_time": storage.now_str()[:10],
        "role": "user",
        "submit_count": 0,
        "resolve_count": 0,
    }, "register success")


@router.post("/users/admin")
async def create_admin(request: Request, body: UserCreate):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if not is_admin(user):
        return err(403, "权限不足")

    username = body.username
    password = body.password
    if not (3 <= len(username) <= 40):
        return err(400, "用户名长度须为 3-40 个字符")
    if len(password) < 6:
        return err(400, "密码长度至少 6 位")

    users = storage.get_users()
    for u in users.values():
        if u.get("username") == username:
            return err(400, "用户名已存在")

    user_id = storage.new_id()
    users[user_id] = {
        "user_id": user_id,
        "username": username,
        "password_hash": _hash_password(password),
        "join_time": storage.now_str()[:10],
        "role": "admin",
        "submit_count": 0,
        "resolve_count": 0,
    }
    storage.save_users(users)
    return ok({"user_id": user_id, "username": username})


@router.get("/users/")
async def list_users(request: Request, page: int = None, page_size: int = None):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if not is_admin(user):
        return err(403, "权限不足")
    if page is not None and page_size is None:
        return err(400, "提供 page 时必须同时提供 page_size")

    users = storage.get_users()
    items = list(users.values())
    items.sort(key=lambda x: x.get("user_id"))
    total = len(items)

    if page is not None and page_size is not None:
        start = (page - 1) * page_size
        items = items[start:start + page_size]

    data = []
    for u in items:
        data.append({
            "user_id": u["user_id"],
            "username": u["username"],
            "role": u.get("role", "user"),
            "join_time": u.get("join_time", ""),
            "submit_count": u.get("submit_count", 0),
            "resolve_count": u.get("resolve_count", 0),
            "attempted_count": len(u.get("attempted_problems") or []),
        })
    return ok({"total": total, "users": data})


@router.get("/users/{user_id}")
async def get_user_info(request: Request, user_id: str):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")
    target = storage.get_users().get(user_id)
    if target is None:
        return err(404, "用户不存在")
    if not is_admin(user) and user["user_id"] != user_id:
        return err(403, "权限不足")
    return ok(_user_public(target))


@router.put("/users/{user_id}/role")
async def update_role(request: Request, user_id: str, body: RoleUpdate):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if not is_admin(user):
        return err(403, "权限不足")
    if body.role not in ("admin", "user", "banned"):
        return err(400, "无效的角色")

    users = storage.get_users()
    target = users.get(user_id)
    if target is None:
        return err(404, "用户不存在")
    # 内置 admin 账号锁定为管理员：禁止改角色/封禁，防止误操作把唯一管理员降权导致系统无法管理
    if target.get("username") == "admin":
        return err(403, "admin 账号已锁定为管理员，无法修改角色")
    target["role"] = body.role
    storage.save_users(users)
    return ok({"user_id": user_id, "role": body.role}, "role updated")
