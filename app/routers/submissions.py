"""Step2/3/5 提交评测路由：提交、详情、列表、重新评测、日志。"""
from fastapi import APIRouter, Request

from .. import storage
from ..deps import get_current_user, is_admin, check_rate_limit
from ..models import SubmissionCreate
from ..schemas import ok, err
from ..judge import queue
from ..judge.queue import enqueue

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


@router.post("/")
async def create_submission(request: Request, body: SubmissionCreate):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")

    problem = storage.get_problem(body.problem_id)
    if problem is None:
        return err(404, "题目不存在")

    langs = storage.get_languages()
    if body.language not in langs:
        return err(404, "语言不存在")

    # 频率限制
    if not check_rate_limit(user["user_id"]):
        return err(429, "提交过于频繁，请稍后再试")

    submission_id = storage.new_id()
    submission = {
        "submission_id": submission_id,
        "user_id": user["user_id"],
        "username": user.get("username", ""),
        "problem_id": body.problem_id,
        "language": body.language,
        "code": body.code,
        "submit_time": storage.now_str(),
        "status": "pending",
        "score": None,
        "counts": None,
        "compile_info": None,
        "run_info": None,
        "error_info": None,
        "details": None,
    }
    storage.save_submission(submission)
    enqueue(submission_id)
    return ok({"submission_id": submission_id, "status": "pending"})


@router.get("/")
async def list_submissions(
    request: Request,
    user_id: str = None,
    problem_id: str = None,
    status: str = None,
    page: int = None,
    page_size: int = None,
):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")

    # page 非空但 page_size 空 → 参数错误
    if page is not None and page_size is None:
        return err(400, "提供 page 时必须同时提供 page_size")

    # 权限：非管理员只能看自己；管理员可不指定 user_id 查看所有人
    if not is_admin(user):
        if user_id is not None and user_id != user["user_id"]:
            return err(403, "权限不足")
        user_id = user["user_id"]

    ids = storage.list_submission_ids()
    subs = []
    for sid in ids:
        s = storage.get_submission(sid)
        if s is None:
            continue
        if user_id is not None and s.get("user_id") != user_id:
            continue
        if problem_id is not None and s.get("problem_id") != problem_id:
            continue
        if status is not None and s.get("status") != status:
            continue
        subs.append(s)

    # 按提交时间倒序（新提交在前）
    subs.sort(key=lambda x: x.get("submit_time", ""), reverse=True)
    total = len(subs)

    # 分页
    if page is not None and page_size is not None:
        start = (page - 1) * page_size
        subs = subs[start:start + page_size]

    # 列表返回摘要信息：统一带提交者/题目/时间等展示字段，error/pending 时 score 等为 None
    result = []
    for s in subs:
        problem = storage.get_problem(s.get("problem_id", ""))
        result.append({
            "submission_id": s["submission_id"],
            "status": s["status"],
            "username": s.get("username", ""),
            "user_id": s.get("user_id", ""),
            "problem_id": s.get("problem_id", ""),
            "problem_title": problem.get("title", "") if problem else "",
            "language": s.get("language", ""),
            "submit_time": s.get("submit_time", ""),
            "score": s.get("score") if s["status"] == "success" else None,
            "counts": s.get("counts") if s["status"] == "success" else None,
        })
    return ok({"total": total, "submissions": result})


@router.get("/{submission_id}")
async def get_submission_info(request: Request, submission_id: str):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")
    s = storage.get_submission(submission_id)
    if s is None:
        return err(404, "提交不存在")
    # 仅本人或管理员
    if not is_admin(user) and s.get("user_id") != user["user_id"]:
        return err(403, "权限不足")

    if s["status"] == "pending":
        return ok({
            "submission_id": s["submission_id"],
            "status": "pending",
            "problem_id": s.get("problem_id", ""),
            "username": s.get("username", ""),
            "language": s.get("language", ""),
            "submit_time": s.get("submit_time", ""),
        })

    problem = storage.get_problem(s.get("problem_id", ""))
    return ok({
        "submission_id": s["submission_id"],
        "status": s["status"],
        "problem_id": s.get("problem_id", ""),
        "problem_title": problem.get("title", "") if problem else "",
        "username": s.get("username", ""),
        "language": s.get("language", ""),
        "submit_time": s.get("submit_time", ""),
        "score": s.get("score"),
        "counts": s.get("counts"),
        "compile_info": s.get("compile_info"),
        "run_info": s.get("run_info"),
        "error_info": s.get("error_info", ""),
    })


@router.get("/{submission_id}/log")
async def get_submission_log(request: Request, submission_id: str):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")
    s = storage.get_submission(submission_id)
    if s is None:
        return err(404, "提交不存在")

    problem = storage.get_problem(s.get("problem_id", ""))
    is_owner = s.get("user_id") == user["user_id"]
    is_admin_user = is_admin(user)
    public_cases = bool(problem and problem.get("public_cases", False))

    # 权限：本人 / 管理员 / public_cases 公开
    if not (is_owner or is_admin_user or public_cases):
        storage.append_audit_log({
            "user_id": user["user_id"],
            "problem_id": s.get("problem_id", ""),
            "action": "view_log",
            "time": storage.now_str(),
            "status": 403,
        })
        return err(403, "权限不足")

    # 记录审计
    storage.append_audit_log({
        "user_id": user["user_id"],
        "problem_id": s.get("problem_id", ""),
        "action": "view_log",
        "time": storage.now_str(),
        "status": 200,
    })

    details = s.get("details")
    # 非管理员且非本人，仅 public_cases 可见 details
    if not is_admin_user and not is_owner:
        # 公开时也可见，但按文档 details 用户可见需 public_cases
        pass

    if details is None:
        return ok({"details": [], "score": s.get("score"), "counts": s.get("counts")})

    # 管理员/本人返回完整 details；否则（public_cases）也返回 details
    return ok({
        "details": details,
        "score": s.get("score"),
        "counts": s.get("counts"),
    })


@router.put("/{submission_id}/rejudge")
async def rejudge(request: Request, submission_id: str):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if not is_admin(user):
        return err(403, "权限不足")
    s = storage.get_submission(submission_id)
    if s is None:
        return err(404, "提交不存在")
    if s["status"] == "pending":
        return err(409, "该提交正在评测中")

    # 重置为 pending，重新入队
    s["status"] = "pending"
    s["score"] = None
    s["counts"] = None
    s["compile_info"] = None
    s["run_info"] = None
    s["error_info"] = None
    s["details"] = None
    storage.save_submission(s)
    enqueue(submission_id)
    return ok({"submission_id": submission_id, "status": "pending"}, "rejudge started")
