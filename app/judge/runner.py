"""异步进程执行器。

在 Windows 上用 asyncio.create_subprocess_exec 异步拉起子进程，
配合 asyncio.wait_for 做时间限制，psutil 轮询做内存限制。
"""
import asyncio
import os
from dataclasses import dataclass

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from .. import config


@dataclass
class RunResult:
    """一次运行/编译的结果。"""
    returncode: int          # 退出码
    stdout: str              # 标准输出
    stderr: str              # 标准错误
    time_cost: float         # 耗时（秒）
    memory_cost: float       # 峰值内存（MB）
    timed_out: bool = False
    memory_exceeded: bool = False
    cancelled: bool = False  # 被用户手动取消（停止评测）
    error: str = ""          # 执行器层面的异常信息


async def _monitor_memory(proc, limit_mb: float, flag: dict) -> None:
    """后台协程轮询子进程内存，记录峰值并超限时杀掉。"""
    if psutil is None:
        return
    try:
        p = psutil.Process(proc.pid)
        while True:
            if proc.returncode is not None:
                break
            try:
                rss = p.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            # 持续记录峰值（含子进程）
            peak = rss
            try:
                for child in p.children(recursive=True):
                    peak += child.memory_info().rss
            except Exception:
                pass
            if peak > flag["peak"]:
                flag["peak"] = peak
            if peak > limit_mb * 1024 * 1024:
                flag["mle"] = True
                _kill(proc)
                break
            await asyncio.sleep(0.05)
    except Exception:
        pass


def _kill(proc) -> None:
    """尽力终止进程（含子进程）。"""
    try:
        if psutil is not None:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
            parent.kill()
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


async def run_command(
    cmd: list[str],
    stdin_data: str = "",
    time_limit: float = 3.0,
    memory_limit: float = 128.0,
    cwd: str = None,
    env: dict = None,
    cancel_check=None,
) -> RunResult:
    """异步执行一条命令，返回 RunResult。

    - time_limit：秒，超时返回 timed_out=True
    - memory_limit：MB，超限返回 memory_exceeded=True
    - cancel_check：可选，返回 True 表示请求取消——运行期间每 0.5s 轮询
      一次，命中即杀进程返回 cancelled=True（实现「停止评测」）。
    """
    cwd = cwd or config.JUDGE_TMP_DIR
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    start = asyncio.get_event_loop().time()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=full_env,
    )

    flag: dict = {"mle": False, "peak": 0}
    monitor = asyncio.ensure_future(_monitor_memory(proc, memory_limit, flag))

    timed_out = False
    cancelled = False
    try:
        if cancel_check is not None:
            # 先喂输入（写完关闭 stdin，通知用户程序输入结束），再做分块轮询等待。
            try:
                proc.stdin.write(stdin_data.encode("utf-8", errors="replace"))
                await proc.stdin.drain()
                proc.stdin.close()
            except Exception:
                pass
            # 分块等待：用 wait() 轮询代替长时 communicate，期间每 0.5s 查一次
            # 取消标记——单个测试点卡住（如 1000s 时限的死循环）也能被立即中止。
            while True:
                if cancel_check():
                    cancelled = True
                    break
                try:
                    await asyncio.wait_for(proc.wait(), timeout=0.5)
                    break  # 进程已自行退出
                except asyncio.TimeoutError:
                    continue
            # 进程已退出（或已杀），兜底读取残留输出（有界等待，防挂起）
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=5.0
                )
            except Exception:
                stdout_b, stderr_b = b"", b""
        else:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(stdin_data.encode("utf-8", errors="replace")),
                timeout=time_limit,
            )
    except asyncio.TimeoutError:
        timed_out = True
        stdout_b, stderr_b = b"", b""
    finally:
        monitor.cancel()
        if timed_out or cancelled:
            _kill(proc)
        # 确保进程被回收：不能用无界 await proc.wait()——
        # 在 Windows Proactor 事件循环下，communicate() 被 wait_for 取消后
        # 其内部未完成的 wait future 可能残留，导致后续 proc.wait() 永久挂起，
        # 进而卡死整个串行评测队列。改用有界等待 + 兜底强杀。
        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                _kill(proc)
            except Exception:
                pass

    elapsed = asyncio.get_event_loop().time() - start

    # 优先用监控协程记录的峰值内存（进程退出后 rss 读不到）
    mem_mb = flag["peak"] / 1024 / 1024
    if mem_mb <= 0 and psutil is not None:
        try:
            mem_mb = psutil.Process(proc.pid).memory_info().rss / 1024 / 1024
        except Exception:
            mem_mb = 0.0

    return RunResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout_b.decode("utf-8", errors="replace"),
        stderr=stderr_b.decode("utf-8", errors="replace"),
        time_cost=round(elapsed, 3),
        memory_cost=round(mem_mb, 2),
        timed_out=timed_out,
        memory_exceeded=flag["mle"],
        cancelled=cancelled,
    )
