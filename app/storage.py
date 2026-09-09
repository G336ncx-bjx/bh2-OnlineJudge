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

# 读缓存：path -> (mtime_ns, size, data)
# 基于文件 mtime 校验，文件未变化时直接返回缓存，避免列表接口逐个读文件导致慢。
# 写操作通过 os.replace 原子替换文件，必然改变 mtime，因此下次读会自动刷新缓存，
# 数据新鲜性有保证，无需手动失效。
_read_cache: dict[str, tuple[int, int, Any]] = {}


# ---------------------------------------------------------------- 通用工具
def _read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        _read_cache.pop(path, None)
        return default
    try:
        st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
        cached = _read_cache.get(path)
        if cached is not None and cached[0] == key[0] and cached[1] == key[1]:
            return cached[2]
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _read_cache[path] = (key[0], key[1], data)
        return data
    except (json.JSONDecodeError, OSError):
        _read_cache.pop(path, None)
        return default


def _write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    # 写后主动失效缓存（避免同进程内 mtime 相同导致的极小概率脏读）
    _read_cache.pop(path, None)


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
    _read_cache.pop(path, None)
    if os.path.exists(path):
        os.remove(path)


def delete_submissions_of_problem(problem_id: str) -> None:
    """级联删除某题目的所有提交记录文件（题目删除时调用）。"""
    if not os.path.isdir(config.SUBMISSIONS_DIR):
        return
    for sid in list_submission_ids():
        s = get_submission(sid)
        if s is not None and s.get("problem_id") == problem_id:
            path = os.path.join(config.SUBMISSIONS_DIR, f"{sid}.json")
            _read_cache.pop(path, None)
            try:
                os.remove(path)
            except OSError:
                pass


def remove_audit_logs_of_problem(problem_id: str) -> None:
    """从审计日志中移除某题目的所有访问记录（题目删除时调用）。"""
    with _lock:
        logs = _read_json(config.AUDIT_LOGS_FILE, [])
        kept = [e for e in logs if e.get("problem_id") != problem_id]
        if len(kept) != len(logs):
            _write_json(config.AUDIT_LOGS_FILE, kept)


def remove_problem_from_users_resolved(problem_id: str) -> None:
    """删除题目时同步回退用户统计。

    题目被删除后，该题的历史提交与通过记录一并清除，因此：
    - submit_count 减去该用户对这道题的提交数；
    - 若该题在用户「已通过题目」集合中，从集合移除并将 resolve_count 减 1
      （与「一个题目贡献一次」的口径保持一致）；
    - 若该题在用户「提交过的题目」集合中，同样移除（与 attempted 口径一致）。
    """
    users = get_users()
    # 统计每个用户对这道题的提交数
    sub_counts: dict[str, int] = {}
    for sid in list_submission_ids():
        s = get_submission(sid)
        if s is not None and s.get("problem_id") == problem_id:
            uid = s.get("user_id")
            if uid:
                sub_counts[uid] = sub_counts.get(uid, 0) + 1
    changed = False
    for uid, u in users.items():
        if uid in sub_counts:
            u["submit_count"] = max(0, u.get("submit_count", 0) - sub_counts[uid])
            changed = True
        resolved = u.get("resolved_problems")
        if isinstance(resolved, list) and problem_id in resolved:
            u["resolved_problems"] = [p for p in resolved if p != problem_id]
            u["resolve_count"] = max(0, u.get("resolve_count", 0) - 1)
            changed = True
        attempted = u.get("attempted_problems")
        if isinstance(attempted, list) and problem_id in attempted:
            u["attempted_problems"] = [p for p in attempted if p != problem_id]
            changed = True
    if changed:
        save_users(users)


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
        _read_cache.clear()
