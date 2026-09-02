"""Step2 语言管理路由：动态注册、查询语言列表。"""
from fastapi import APIRouter, Request

from .. import storage
from ..deps import get_current_user
from ..models import LanguageCreate
from ..schemas import ok, err

router = APIRouter(prefix="/api/languages", tags=["languages"])


@router.get("/")
async def list_languages(request: Request):
    # 语言列表不要求登录（文档中无权限限制）
    langs = storage.get_languages()
    return ok({"name": list(langs.keys())})


@router.post("/")
async def register_language(request: Request, body: LanguageCreate):
    user = get_current_user(request)
    if user is None:
        return err(401, "未登录")
    if user.get("role") == "banned":
        return err(403, "用户已被封禁")
    data = body.model_dump()
    if not data.get("name") or not data.get("file_ext") or not data.get("run_cmd"):
        return err(400, "name、file_ext、run_cmd 不能为空")

    langs = storage.get_languages()
    if data["name"] in langs:
        return err(409, "语言已存在")

    langs[data["name"]] = {
        "name": data["name"],
        "file_ext": data["file_ext"],
        "compile_cmd": data.get("compile_cmd"),
        "run_cmd": data["run_cmd"],
        "time_limit": data.get("time_limit"),
        "memory_limit": data.get("memory_limit"),
    }
    storage.save_languages(langs)
    return ok({"name": data["name"]}, "language registered")
