"""FastAPI 主入口。"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from . import config, storage
from .schemas import ok, err
from .deps import get_current_user, is_admin, reset_rate_limits
from .judge import queue
from .routers import problems, languages, submissions, users, logs, ai
from .routers.users import ensure_initial_admin
from .ai import engine as ai_engine

app = FastAPI(title="OJ System", version="1.0.0")


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    """把 Pydantic 字段校验错误统一转成中文提示。"""
    errors = exc.errors()
    msgs = []
    for e in errors:
        loc = e.get("loc", [])
        field = loc[-1] if loc else "请求体"
        # 常见校验错误类型的中文翻译
        etype = e.get("type", "")
        if etype == "missing":
            msgs.append(f"字段「{field}」缺失")
        elif "required" in etype:
            msgs.append(f"字段「{field}」不能为空")
        elif etype in ("string_type", "int_type", "float_type", "list_type", "bool_type"):
            msgs.append(f"字段「{field}」类型不正确")
        else:
            msg = e.get("msg", "")
            msgs.append(f"字段「{field}」校验失败: {msg}")
    return JSONResponse(status_code=400, content={"code": 400, "msg": "；".join(msgs), "data": None})

# Session 中间件
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET_KEY)

# CORS（前端 Streamlit 跨端口调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载路由
app.include_router(problems.router)
app.include_router(languages.router)
app.include_router(submissions.router)
app.include_router(users.router)
app.include_router(logs.router)
app.include_router(ai.router)


@app.on_event("startup")
async def on_startup():
    config.ensure_dirs()
    ensure_initial_admin()
    _seed_languages()
    queue.start_worker()
    # 启动恢复：把磁盘上遗留的 pending 提交重新入队（服务重启前中断的评测不丢）
    requeued = queue.requeue_stale_pending()
    if requeued:
        print(f"[startup] requeued {requeued} stale pending submission(s)")
    # 启动恢复：AI 命题协程是内存态后台任务，重启后遗留的
    # pending/running 任务标记为 failed，避免永久卡住
    stale = ai_engine.recover_stale_tasks()
    if stale:
        print(f"[startup] marked {stale} stale ai task(s) as failed")


@app.on_event("shutdown")
async def on_shutdown():
    await queue.stop_worker()


def _seed_languages() -> None:
    """初始化内置语言 python / cpp。"""
    langs = storage.get_languages()
    if "python" not in langs:
        langs["python"] = {
            "name": "python",
            "file_ext": ".py",
            "compile_cmd": None,
            "run_cmd": "python {src}",
            "time_limit": 1.0,
            "memory_limit": 128,
        }
    if "cpp" not in langs:
        langs["cpp"] = {
            "name": "cpp",
            "file_ext": ".cpp",
            "compile_cmd": "g++ {src} -o {exe}",
            "run_cmd": "{exe}",
            "time_limit": 1.0,
            "memory_limit": 128,
        }
    # 兼容修复：早期曾写入 -std=c++17，但本机 MinGW 8.1 的 stdc++.h 与
    # c++17 的 filesystem 库冲突导致编译失败，统一回退为默认标准
    elif "-std=" in langs["cpp"].get("compile_cmd", ""):
        langs["cpp"]["compile_cmd"] = "g++ {src} -o {exe}"
    storage.save_languages(langs)


@app.get("/")
async def root():
    return ok({"service": "OJ System", "status": "running"})


@app.post("/api/reset/")
async def system_reset(request: Request):
    """系统重置：清空数据、退出登录、重建初始管理员。"""
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if not is_admin(user):
        return err(403, "权限不足")

    request.session.clear()
    storage.reset_all()
    reset_rate_limits()
    ensure_initial_admin()
    _seed_languages()
    return ok(None, "system reset successfully")
