"""Step1 题目管理 + Step5 日志可见性路由。"""
from fastapi import APIRouter, Request

from .. import storage
from ..deps import get_current_user, is_admin
from ..models import ProblemCreate
from ..schemas import ok, err

router = APIRouter(prefix="/api/problems", tags=["problems"])

# 必选字段：字段名 -> 中文标签（用于错误提示）
REQUIRED_FIELDS = [
    ("id", "题目标识"),
    ("title", "标题"),
    ("description", "题目描述"),
    ("input_description", "输入格式说明"),
    ("output_description", "输出格式说明"),
    ("samples", "样例"),
    ("constraints", "数据限制"),
    ("testcases", "测试点"),
]


def _validate_problem(p: dict) -> str | None:
    """校验题目配置，返回错误信息或 None。"""
    for field, label in REQUIRED_FIELDS:
        if field not in p or p[field] in (None, ""):
            return f"字段「{label}」不能为空"
    if not isinstance(p["samples"], list):
        return "样例必须是列表"
    if not isinstance(p["testcases"], list):
        return "测试点必须是列表"
    if not p["samples"]:
        return "样例不能为空列表"
    if not p["testcases"]:
        return "测试点不能为空列表"
    for s in p["samples"]:
        if not isinstance(s, dict) or "input" not in s or "output" not in s:
            return "样例必须包含 input 和 output"
    for t in p["testcases"]:
        if not isinstance(t, dict) or "input" not in t or "output" not in t:
            return "测试点必须包含 input 和 output"
    if not isinstance(p["id"], str) or not p["id"]:
        return "题目标识必须是非空字符串"
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
    # 补全可选字段默认值（api.md：默认字段需返回本类型默认值，str->""、list->[]）
    p.setdefault("hint", "")
    p.setdefault("source", "")
    p.setdefault("tags", [])
    p.setdefault("time_limit", 3.0)
    p.setdefault("memory_limit", 128)
    p.setdefault("author", "")
    p.setdefault("difficulty", "")
    p.setdefault("public_cases", False)
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
    # 级联删除：先回退用户统计（需在提交删除前统计），再删题目/提交/审计
    storage.remove_problem_from_users_resolved(problem_id)
    storage.delete_problem(problem_id)
    storage.delete_submissions_of_problem(problem_id)
    storage.remove_audit_logs_of_problem(problem_id)
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
