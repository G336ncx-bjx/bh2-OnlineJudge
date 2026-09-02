"""Step1 题目管理 + Step5 日志可见性路由。"""
from fastapi import APIRouter, Request

from .. import storage
from ..deps import get_current_user, is_admin
from ..models import ProblemCreate
from ..schemas import ok, err

router = APIRouter(prefix="/api/problems", tags=["problems"])

# 必选字段
REQUIRED_FIELDS = [
    "id", "title", "description", "input_description",
    "output_description", "samples", "constraints", "testcases",
]


def _validate_problem(p: dict) -> str | None:
    """校验题目配置，返回错误信息或 None。"""
    for field in REQUIRED_FIELDS:
        if field not in p or p[field] in (None, ""):
            return f"missing field: {field}"
    if not isinstance(p["samples"], list):
        return "samples must be a list"
    if not isinstance(p["testcases"], list):
        return "testcases must be a list"
    for s in p["samples"]:
        if not isinstance(s, dict) or "input" not in s or "output" not in s:
            return "sample must contain input and output"
    for t in p["testcases"]:
        if not isinstance(t, dict) or "input" not in t or "output" not in t:
            return "testcase must contain input and output"
    if not isinstance(p["id"], str) or not p["id"]:
        return "id must be a non-empty string"
    return None


@router.get("/")
async def list_problems(request: Request):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")
    ids = storage.list_problem_ids()
    data = []
    for pid in ids:
        p = storage.get_problem(pid)
        if p:
            data.append({"id": p["id"], "title": p["title"]})
    return ok(data)


@router.post("/")
async def create_problem(request: Request, body: ProblemCreate):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")
    p = body.model_dump()
    err_msg = _validate_problem(p)
    if err_msg:
        return err(400, err_msg)
    if storage.get_problem(p["id"]) is not None:
        return err(409, "题目 id 已存在")
    p.setdefault("hint", "")
    p.setdefault("source", "")
    p.setdefault("tags", [])
    p.setdefault("time_limit", 3.0)
    p.setdefault("memory_limit", 128)
    p.setdefault("author", "")
    p.setdefault("difficulty", "")
    p.setdefault("public_cases", False)
    storage.save_problem(p)
    return ok({"id": p["id"]}, "add success")


@router.get("/{problem_id}")
async def get_problem_info(request: Request, problem_id: str):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")
    p = storage.get_problem(problem_id)
    if p is None:
        return err(404, "题目不存在")
    return ok(p)


@router.put("/{problem_id}")
async def update_problem(request: Request, problem_id: str, body: ProblemCreate):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")
    p = body.model_dump()
    if p.get("id") != problem_id:
        return err(400, "id 不一致")
    err_msg = _validate_problem(p)
    if err_msg:
        return err(400, err_msg)
    existing = storage.get_problem(problem_id)
    if existing is None:
        return err(404, "题目不存在")
    # 保留 public_cases 配置
    p["public_cases"] = existing.get("public_cases", False)
    storage.save_problem(p)
    return ok({"id": problem_id}, "update success")


@router.delete("/{problem_id}")
async def delete_problem(request: Request, problem_id: str):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if not is_admin(user):
        return err(403, "权限不足")
    if storage.get_problem(problem_id) is None:
        return err(404, "题目不存在")
    storage.delete_problem(problem_id)
    return ok({"id": problem_id}, "delete success")


@router.put("/{problem_id}/log_visibility")
async def set_log_visibility(request: Request, problem_id: str):
    """Step5：配置日志可见性（public_cases）。"""
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if not is_admin(user):
        return err(403, "权限不足")
    p = storage.get_problem(problem_id)
    if p is None:
        return err(404, "题目不存在")
    body = await request.json()
    public_cases = body.get("public_cases", False)
    if not isinstance(public_cases, bool):
        return err(400, "public_cases 必须是布尔值")
    p["public_cases"] = public_cases
    storage.save_problem(p)
    return ok({"problem_id": problem_id, "public_cases": public_cases}, "log visibility updated")
