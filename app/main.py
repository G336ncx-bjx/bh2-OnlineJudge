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
    return JSONResponse(status_code=422, content={"code": 422, "msg": "；".join(msgs), "data": None})

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
        return err(401, "未登录")
    if not is_admin(user):
        return err(403, "权限不足")

    request.session.clear()
    storage.reset_all()
    reset_rate_limits()
    ensure_initial_admin()
    _seed_languages()
    return ok(None, "system reset successfully")
