"""评测任务队列：asyncio.Queue + 后台 worker 协程。"""
import asyncio

from .. import storage
from .engine import judge_submission

# 任务队列（submission_id）
_queue: asyncio.Queue = asyncio.Queue()

# 后台 worker 任务引用
_worker_task: asyncio.Task = None

# 取消标记：submission_id -> True，评测引擎在每个测试点之间检查，
# 发现标记即中止剩余测试点；worker 据此把提交标记为 error（手动取消）。
cancel_flags: dict[str, bool] = {}


def request_cancel(submission_id: str) -> None:
    """请求取消某条正在评测的提交（置标记，由 worker/engine 协作生效）。"""
    cancel_flags[submission_id] = True


def enqueue(submission_id: str) -> None:
    """将提交任务放入队列。"""
    _queue.put_nowait(submission_id)


def requeue_stale_pending() -> int:
    """启动恢复：把磁盘上遗留的 pending 提交重新入队（服务重启后兜底）。

    返回重新入队的数量。
    """
    count = 0
    for sid in storage.list_submission_ids():
        s = storage.get_submission(sid)
        if s is not None and s.get("status") == "pending":
            _queue.put_nowait(sid)
            count += 1
    return count


async def _worker() -> None:
    """后台评测 worker：串行消费队列（满足单用户任务要求）。"""
    while True:
        submission_id = await _queue.get()
        try:
            submission = storage.get_submission(submission_id)
            if submission is None or submission.get("status") != "pending":
                continue
            # 评测前检查：题目已被删除 → 丢弃该任务（不评测、不写回）
            if storage.get_problem(submission.get("problem_id")) is None:
                continue
            # 排队期间已被取消 → 不评测，直接标记 error
            if cancel_flags.pop(submission_id, False):
                submission["status"] = "error"
                submission["error_info"] = "评测已被用户手动取消"
                submission["score"] = 0
                submission["counts"] = 0
                submission["details"] = []
                storage.save_submission(submission)
                continue
            # 评测
            result = await judge_submission(submission)
            # 评测中途取消：不写回正常结果、不更新统计，标记 error 说明原因
            if cancel_flags.pop(submission_id, False):
                result["status"] = "error"
                result["error_info"] = "评测已被用户手动取消"
                result["score"] = 0
                result["counts"] = 0
                result["details"] = []
            # 评测后复查：评测期间题目被删除 → 丢弃结果（不写回、不计数）
            if storage.get_problem(result.get("problem_id")) is None:
                continue
            # 更新用户提交/解决计数
            _update_user_stats(result)
            storage.save_submission(result)
        except Exception:
            # 评测异常兜底：标记 error
            try:
                submission = storage.get_submission(submission_id)
                if submission is not None:
                    submission["status"] = "error"
                    submission["error_info"] = "评测工作进程异常"
                    storage.save_submission(submission)
            except Exception:
                pass
        finally:
            _queue.task_done()


def _is_full_score(submission: dict) -> bool:
    """判断提交是否满分（通过该题）。"""
    return (submission.get("score", 0) > 0
            and submission.get("counts", 0) > 0
            and submission["score"] >= submission["counts"] * 10)


def _rebuild_resolved(user_id: str) -> list[str]:
    """从该用户全部历史提交中重建「已通过题目」集合（一题一次）。

    用于旧数据向后兼容：历史实现里同题多次 AC 会重复计数 resolve_count，
    重建后 resolve_count 与集合长度一致，即「一个题目贡献一次」。
    """
    resolved: list[str] = []
    for sid in storage.list_submission_ids():
        s = storage.get_submission(sid)
        if s is None or s.get("user_id") != user_id:
            continue
        if not _is_full_score(s):
            continue
        pid = s.get("problem_id")
        if pid and pid not in resolved:
            resolved.append(pid)
    return resolved


def _rebuild_attempted(user_id: str) -> list[str]:
    """从该用户全部历史提交中重建「提交过的题目」集合（一题一次）。"""
    attempted: list[str] = []
    for sid in storage.list_submission_ids():
        s = storage.get_submission(sid)
        if s is None or s.get("user_id") != user_id:
            continue
        pid = s.get("problem_id")
        if pid and pid not in attempted:
            attempted.append(pid)
    return attempted


def _update_user_stats(submission: dict) -> None:
    """更新用户的 submit_count / resolve_count / attempted_count。

    - submit_count：每次提交 +1；
    - attempted_problems：提交过的题目集合（按题去重，一题一次）；
    - resolved_problems：通过的题目集合（按题去重，一题一次）。
    通过率 = resolve_count / attempted_count（提交过的题为基数）。
    """
    user_id = submission.get("user_id")
    if not user_id:
        return
    users = storage.get_users()
    user = users.get(user_id)
    if user is None:
        return
    user.setdefault("submit_count", 0)
    user["submit_count"] += 1
    # 惰性初始化「提交过题目」与「已通过题目」集合：旧数据没有字段时从历史提交重建
    if "attempted_problems" not in user:
        user["attempted_problems"] = _rebuild_attempted(user_id)
    if "resolved_problems" not in user:
        user["resolved_problems"] = _rebuild_resolved(user_id)
        user["resolve_count"] = len(user["resolved_problems"])
    # 本题未在「提交过」集合 → 加入（提交基数按题去重）
    pid = submission.get("problem_id")
    if pid and pid not in user["attempted_problems"]:
        user["attempted_problems"].append(pid)
    # 满分且该题尚未通过 → 通过数 +1（同题重复 AC 不重复计数）
    if _is_full_score(submission):
        if pid and pid not in user["resolved_problems"]:
            user["resolved_problems"].append(pid)
            user.setdefault("resolve_count", 0)
            user["resolve_count"] += 1
    storage.save_users(users)


def start_worker() -> None:
    """启动后台评测 worker（在事件循环内调用）。"""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker())


async def stop_worker() -> None:
    """停止 worker（优雅关闭）。"""
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
