"""Step5 日志访问审计路由。"""
from fastapi import APIRouter, Request

from .. import storage
from ..deps import get_current_user, is_admin
from ..schemas import ok, err

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/access/")
async def list_access_logs(
    request: Request,
    user_id: str = None,
    problem_id: str = None,
    page: int = None,
    page_size: int = None,
):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if not is_admin(user):
        return err(403, "权限不足")
    if page is not None and page_size is None:
        return err(400, "提供 page 时必须同时提供 page_size")

    logs = storage.get_audit_logs()
    result = []
    for entry in logs:
        if user_id is not None and entry.get("user_id") != user_id:
            continue
        if problem_id is not None and entry.get("problem_id") != problem_id:
            continue
        result.append(entry)

    result.reverse()  # 最新在前
    total = len(result)

    if page is not None and page_size is not None:
        start = (page - 1) * page_size
        result = result[start:start + page_size]

    return ok({"total": total, "logs": result})
