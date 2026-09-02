"""JSON 文件存储层。

所有数据的读写都集中在这里，用文件锁保证简单并发安全。
题目：data/problems/{id}.json
语言：data/languages.json
用户：data/users.json
提交：data/submissions/{id}.json
审计：data/audit_logs.json
"""
import json
import os
import threading
import time
import uuid
from typing import Any, Optional

from . import config

# 全局读写锁（课程项目规模小，单一锁足够）
_lock = threading.RLock()


# ---------------------------------------------------------------- 通用工具
def _read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def new_id() -> str:
    """生成短 id（提交记录用）。"""
    return uuid.uuid4().hex[:12]


def now_str() -> str:
    """当前时间字符串 YYYY-MM-DD HH:MM:SS。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 题目
def list_problem_ids() -> list[str]:
    """返回所有题目 id（按文件名排序）。"""
    if not os.path.isdir(config.PROBLEMS_DIR):
        return []
    ids = [
        f[:-5] for f in os.listdir(config.PROBLEMS_DIR) if f.endswith(".json")
    ]
    return sorted(ids)


def get_problem(problem_id: str) -> Optional[dict]:
    path = os.path.join(config.PROBLEMS_DIR, f"{problem_id}.json")
    return _read_json(path, None)


def save_problem(problem: dict) -> None:
    path = os.path.join(config.PROBLEMS_DIR, f"{problem['id']}.json")
    _write_json(path, problem)


def delete_problem(problem_id: str) -> None:
    path = os.path.join(config.PROBLEMS_DIR, f"{problem_id}.json")
    if os.path.exists(path):
        os.remove(path)


# ---------------------------------------------------------------- 语言
def get_languages() -> dict:
    """返回 {name: config}。"""
    return _read_json(config.LANGUAGES_FILE, {})


def save_languages(langs: dict) -> None:
    _write_json(config.LANGUAGES_FILE, langs)


# ---------------------------------------------------------------- 用户
def get_users() -> dict:
    """返回 {user_id: user}。"""
    return _read_json(config.USERS_FILE, {})


def save_users(users: dict) -> None:
    _write_json(config.USERS_FILE, users)


# ---------------------------------------------------------------- 提交
def get_submission(submission_id: str) -> Optional[dict]:
    path = os.path.join(config.SUBMISSIONS_DIR, f"{submission_id}.json")
    return _read_json(path, None)


def save_submission(sub: dict) -> None:
    path = os.path.join(config.SUBMISSIONS_DIR, f"{sub['submission_id']}.json")
    _write_json(path, sub)


def list_submission_ids() -> list[str]:
    if not os.path.isdir(config.SUBMISSIONS_DIR):
        return []
    ids = [
        f[:-5] for f in os.listdir(config.SUBMISSIONS_DIR) if f.endswith(".json")
    ]
    return sorted(ids)


# ---------------------------------------------------------------- 审计日志
def get_audit_logs() -> list[dict]:
    return _read_json(config.AUDIT_LOGS_FILE, [])


def append_audit_log(entry: dict) -> None:
    with _lock:
        logs = _read_json(config.AUDIT_LOGS_FILE, [])
        logs.append(entry)
        _write_json(config.AUDIT_LOGS_FILE, logs)


# ---------------------------------------------------------------- 系统重置
def reset_all() -> None:
    """清空题目、提交、用户、审计日志数据。"""
    with _lock:
        for d in (config.PROBLEMS_DIR, config.SUBMISSIONS_DIR):
            if os.path.isdir(d):
                for f in os.listdir(d):
                    try:
                        os.remove(os.path.join(d, f))
                    except OSError:
                        pass
        for f in (config.LANGUAGES_FILE, config.USERS_FILE, config.AUDIT_LOGS_FILE):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
