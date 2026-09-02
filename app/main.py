"""FastAPI 主入口。"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from . import config, storage
from .schemas import ok, err
from .deps import get_current_user, is_admin, reset_rate_limits
from .judge import queue
from .routers import problems, languages, submissions, users, logs, ai
from .routers.users import ensure_initial_admin

app = FastAPI(title="OJ System", version="1.0.0")

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
    storage.save_languages(langs)


@app.get("/")
async def root():
    return ok({"service": "OJ System", "status": "running"})


@app.post("/api/reset/")
async def system_reset(request: Request):
    """系统重置：清空数据、退出登录、重建初始管理员。"""
    user = get_current_user(request)
    if user is None:
        return err(401, "not logged in")
    if not is_admin(user):
        return err(403, "permission denied")

    request.session.clear()
    storage.reset_all()
    reset_rate_limits()
    ensure_initial_admin()
    _seed_languages()
    return ok(None, "system reset successfully")
