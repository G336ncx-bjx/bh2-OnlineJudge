"""AI 智能命题路由：模型配置、创建任务、查询任务、中断任务。"""
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import storage
from ..deps import get_current_user, is_admin
from ..schemas import ok, err
from ..ai import llm, engine

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ModelConfigBody(BaseModel):
    provider_url: str
    model: str
    api_key: Optional[str] = None
    input_price: Optional[float] = None
    output_price: Optional[float] = None
    price_unit: Optional[int] = None
    currency: Optional[str] = None


class ProblemTaskCreate(BaseModel):
    requirement: str
    problem_id: Optional[str] = None


# ---------------------------------------------------------------- 模型配置
@router.put("/model-config")
async def set_model_config(request: Request, body: ModelConfigBody):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")

    cfg = llm.get_model_config_raw()
    cfg["provider_url"] = body.provider_url
    cfg["model"] = body.model
    # 密钥为空表示「不修改」，避免只改单价时把已存密钥清空
    if body.api_key:
        cfg["api_key"] = body.api_key
    if body.input_price is not None:
        cfg["input_price"] = body.input_price
    if body.output_price is not None:
        cfg["output_price"] = body.output_price
    if body.price_unit is not None:
        cfg["price_unit"] = body.price_unit
    if body.currency is not None:
        cfg["currency"] = body.currency
    llm.save_model_config(cfg)

    return ok({
        "provider_url": cfg["provider_url"],
        "model": cfg["model"],
        "api_key_configured": bool(cfg.get("api_key")),
        "input_price": cfg.get("input_price", 0.0),
        "output_price": cfg.get("output_price", 0.0),
        "price_unit": cfg.get("price_unit", 1000000),
        "currency": cfg.get("currency", "USD"),
    }, "model config updated")


@router.get("/model-config")
async def get_model_config(request: Request):
    """查询模型配置（不含密钥）。"""
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")
    return ok(llm.get_model_config())


# ---------------------------------------------------------------- 命题任务
@router.post("/problem-tasks/")
async def create_problem_task(request: Request, body: ProblemTaskCreate):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")
    if not body.requirement or not body.requirement.strip():
        return err(400, "命题需求不能为空")

    # 校验参考题目存在
    if body.problem_id:
        if storage.get_problem(body.problem_id) is None:
            return err(404, "题目不存在")

    # 校验模型配置
    cfg = llm.get_model_config_raw()
    if not cfg.get("provider_url") or not cfg.get("model"):
        return err(400, "模型未配置")

    task_id = storage.new_id()
    task = engine._new_task(
        task_id, body.requirement.strip(), user["user_id"], body.problem_id
    )
    engine._save_task(task)
    engine.start_task(task_id)

    return ok({"task_id": task_id, "status": "pending"}, "task created")


@router.get("/problem-tasks/")
async def list_problem_tasks(
    request: Request,
    status: str = None,
    page: int = None,
    page_size: int = None,
):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")

    if page is not None and page_size is None:
        return err(400, "提供 page 时必须同时提供 page_size")

    ids = engine.list_task_ids()
    tasks = []
    for tid in ids:
        t = engine._get_task(tid)
        if t is None:
            continue
        # 非管理员只能看自己的任务
        if not is_admin(user) and t.get("user_id") != user["user_id"]:
            continue
        if status is not None and t.get("status") != status:
            continue
        tasks.append(t)

    # 按创建时间倒序（新任务在前）
    tasks.sort(key=lambda x: x.get("created_time", ""), reverse=True)
    total = len(tasks)

    if page is not None and page_size is not None:
        start = (page - 1) * page_size
        tasks = tasks[start:start + page_size]

    result = []
    for t in tasks:
        result.append({
            "task_id": t["task_id"],
            "status": t.get("status", ""),
            "requirement": t.get("requirement", ""),
            "problem_id": t.get("problem_id"),
            "created_time": t.get("created_time", ""),
            "usage": t.get("usage", {}),
        })
    return ok({"total": total, "tasks": result})


@router.get("/problem-tasks/{task_id}")
async def get_problem_task(request: Request, task_id: str):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")

    task = engine._get_task(task_id)
    if task is None:
        return err(404, "任务不存在")
    # 仅创建者或管理员
    if not is_admin(user) and task.get("user_id") != user["user_id"]:
        return err(403, "权限不足")

    return ok({
        "task_id": task["task_id"],
        "status": task["status"],
        "progress": task.get("progress", ""),
        "result": task.get("result"),
        "error_info": task.get("error_info", ""),
        "usage": task.get("usage", {}),
    })


@router.put("/problem-tasks/{task_id}/cancel")
async def cancel_problem_task(request: Request, task_id: str):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")

    task = engine._get_task(task_id)
    if task is None:
        return err(404, "任务不存在")
    if not is_admin(user) and task.get("user_id") != user["user_id"]:
        return err(403, "权限不足")
    if task["status"] in ("completed", "failed", "cancelled"):
        return err(409, "任务已结束")

    task["status"] = "cancelled"
    task["progress"] = "任务已中断"
    engine._save_task(task)
    return ok({"task_id": task_id, "status": "cancelled"}, "task cancelled")
