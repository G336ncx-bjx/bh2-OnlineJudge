"""评测任务队列：asyncio.Queue + 后台 worker 协程。"""
import asyncio

from .. import storage
from .engine import judge_submission

# 任务队列（submission_id）
_queue: asyncio.Queue = asyncio.Queue()

# 后台 worker 任务引用
_worker_task: asyncio.Task = None


def enqueue(submission_id: str) -> None:
    """将提交任务放入队列。"""
    _queue.put_nowait(submission_id)


async def _worker() -> None:
    """后台评测 worker：串行消费队列（满足单用户任务要求）。"""
    while True:
        submission_id = await _queue.get()
        try:
            submission = storage.get_submission(submission_id)
            if submission is None or submission.get("status") != "pending":
                continue
            # 评测
            result = await judge_submission(submission)
            # 更新用户提交/解决计数
            _update_user_stats(result)
            storage.save_submission(result)
        except Exception:
            # 评测异常兜底：标记 error
            try:
                submission = storage.get_submission(submission_id)
                if submission is not None:
                    submission["status"] = "error"
                    submission["error_info"] = "judge worker error"
                    storage.save_submission(submission)
            except Exception:
                pass
        finally:
            _queue.task_done()


def _update_user_stats(submission: dict) -> None:
    """更新用户的 submit_count / resolve_count。"""
    user_id = submission.get("user_id")
    if not user_id:
        return
    users = storage.get_users()
    user = users.get(user_id)
    if user is None:
        return
    user.setdefault("submit_count", 0)
    user["submit_count"] += 1
    # 满分视为通过该题（score == counts * 10 且 counts > 0）
    if (submission.get("score", 0) > 0
            and submission.get("counts", 0) > 0
            and submission["score"] >= submission["counts"] * 10):
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
