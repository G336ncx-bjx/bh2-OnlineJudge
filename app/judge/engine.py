"""评测引擎：语言命令解析、编译/运行、输出比对、状态判定。

测试点状态：AC / WA / TLE / MLE / RE / CE / UNK
评测状态：pending / success / error
"""
import os
import shlex
import shutil
import uuid

from .. import config
from .. import storage
from .runner import run_command, RunResult


def _quote(path: str) -> str:
    """将路径加引号，避免含空格路径被拆分。"""
    return f'"{path}"'


def resolve_placeholders(cmd: str, src_path: str, exe_path: str) -> str:
    """替换命令中的 {src} 和 {exe} 占位符为带引号的实际路径。"""
    return cmd.replace("{src}", _quote(src_path)).replace("{exe}", _quote(exe_path))


def _parse_command(cmd: str) -> list[str]:
    """用 shlex 解析命令，正确处理含空格/引号的参数。"""
    return shlex.split(cmd, posix=True)


def _prepare_temp_dir() -> str:
    """为本次评测创建独立临时目录。"""
    d = os.path.join(config.JUDGE_TMP_DIR, uuid.uuid4().hex)
    os.makedirs(d, exist_ok=True)
    return d


def _normalize_output(s: str) -> str:
    """规范化输出：去除末尾空白、每行行尾空白，忽略最后一行多余换行。

    同时处理 Windows 的 \\r\\n 换行符。
    """
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = s.split("\n")
    # 去掉尾部空行
    while lines and lines[-1].strip() == "":
        lines.pop()
    lines = [ln.rstrip() for ln in lines]
    return "\n".join(lines)


def compare_output(actual: str, expected: str) -> bool:
    return _normalize_output(actual) == _normalize_output(expected)


async def compile_source(lang: dict, src_path: str, exe_path: str, cwd: str,
                         time_limit: float, memory_limit: float) -> RunResult:
    """编译源码（无 compile_cmd 的语言跳过，返回成功结果）。"""
    compile_cmd = lang.get("compile_cmd")
    if not compile_cmd:
        # 解释型语言，无需编译
        return RunResult(0, "", "", 0.0, 0.0)
    full_cmd = resolve_placeholders(compile_cmd, src_path, exe_path)
    parts = _parse_command(full_cmd)
    return await run_command(parts, "", time_limit, memory_limit, cwd=cwd)


async def run_source(lang: dict, src_path: str, exe_path: str, cwd: str,
                     stdin_data: str, time_limit: float, memory_limit: float) -> RunResult:
    """运行用户代码。"""
    run_cmd = lang.get("run_cmd", "")
    full_cmd = resolve_placeholders(run_cmd, src_path, exe_path)
    parts = _parse_command(full_cmd)
    return await run_command(
        parts, stdin_data, time_limit, memory_limit, cwd=cwd
    )


async def judge_submission(submission: dict) -> dict:
    """评测一次提交，原地更新并返回提交 dict。

    返回的 submission 中：
    - status: success / error
    - details: 每个测试点结果
    - score: AC 测试点数 * TESTCASE_SCORE
    """
    submission_id = submission["submission_id"]
    problem_id = submission["problem_id"]
    language_name = submission["language"]

    problem = storage.get_problem(problem_id)
    langs = storage.get_languages()
    lang = langs.get(language_name)

    # 题目或语言不存在 → 评测 error
    if problem is None:
        submission["status"] = "error"
        submission["error_info"] = "题目不存在"
        return submission
    if lang is None:
        submission["status"] = "error"
        submission["error_info"] = "语言不存在"
        return submission

    # 资源限制：题目配置优先，否则用语言默认
    time_limit = problem.get("time_limit") or lang.get("time_limit") or config.DEFAULT_TIME_LIMIT
    memory_limit = problem.get("memory_limit") or lang.get("memory_limit") or config.DEFAULT_MEMORY_LIMIT

    testcases = problem.get("testcases", [])
    file_ext = lang.get("file_ext", ".txt")

    tmp_dir = _prepare_temp_dir()
    src_path = os.path.join(tmp_dir, f"main{file_ext}")
    exe_path = os.path.join(tmp_dir, "main.exe" if os.name == "nt" else "main.out")

    try:
        # 写源码文件
        with open(src_path, "w", encoding="utf-8", newline="") as f:
            f.write(submission["code"])

        # 1. 编译（用独立的编译时限，不复用运行时限，避免编译器冷启动超时误判 CE）
        compile_res = await compile_source(lang, src_path, exe_path, tmp_dir,
                                           config.COMPILE_TIME_LIMIT,
                                           config.COMPILE_MEMORY_LIMIT)

        # 编译信息脱敏：不把 g++ 的原始错误输出（含服务器本地绝对路径、
        # 头文件内部细节）暴露给用户，只保留行号级别的错误摘要。
        compile_msg = compile_res.stderr or compile_res.stdout or ""
        compile_info = {
            "result": "success" if compile_res.returncode == 0 else "failed",
            "message": _summarize_compile_error(compile_msg),
        }

        # 编译失败 → 所有测试点 CE
        if compile_res.returncode != 0:
            details = [
                {
                    "id": i + 1,
                    "result": "CE",
                    "time": 0.0,
                    "memory": 0.0,
                    "input": tc["input"],
                    "output": tc["output"],
                    "expected": tc["output"],
                    "actual": "",
                }
                for i, tc in enumerate(testcases)
            ]
            submission["status"] = "success"
            submission["score"] = 0
            submission["counts"] = len(testcases)
            submission["compile_info"] = compile_info
            submission["run_info"] = {"result": "finished", "message": f"{len(testcases)} test cases finished"}
            submission["error_info"] = ""
            submission["details"] = details
            return submission

        # 2. 逐个测试点运行
        details = []
        ac_count = 0
        for i, tc in enumerate(testcases):
            run_res = await run_source(lang, src_path, exe_path, tmp_dir,
                                       tc["input"], time_limit, memory_limit)
            result, actual = _classify(run_res, tc["output"])
            if result == "AC":
                ac_count += 1
            details.append({
                "id": i + 1,
                "result": result,
                "time": run_res.time_cost,
                "memory": run_res.memory_cost,
                "input": tc["input"],
                "output": tc["output"],
                "expected": tc["output"],
                "actual": _normalize_output(actual),
            })

        submission["status"] = "success"
        submission["score"] = ac_count * config.TESTCASE_SCORE
        submission["counts"] = len(testcases)
        submission["compile_info"] = compile_info
        submission["run_info"] = {"result": "finished", "message": f"{len(testcases)} test cases finished"}
        submission["error_info"] = ""
        submission["details"] = details
        return submission

    except Exception as e:  # 未知异常 → 评测 error
        submission["status"] = "error"
        submission["error_info"] = f"评测出错: {type(e).__name__}"
        return submission
    finally:
        # 清理临时目录
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _summarize_compile_error(raw: str) -> str:
    """从 g++ 原始错误输出中提取用户友好的错误摘要。

    - 去掉 #include 链（In file included from ...）与服务器本地绝对路径；
    - 只保留 main.cpp 里出错的行号与错误行，方便定位；
    - 无有效信息时返回精简的错误头几行（截断防过大）。
    """
    if not raw:
        return ""
    lines = raw.replace("\r\n", "\n").split("\n")
    kept = []
    for ln in lines:
        # 丢弃 include 链和包含服务器路径的行
        if ln.startswith("In file included"):
            continue
        if "main.cpp" in ln and (": error:" in ln or ": warning:" in ln):
            kept.append(ln.strip())
        # 保留紧跟错误的具体位置行（形如 `   xxx ^~~~` 不保留；保留 "error:" 摘要）
    if kept:
        # 去重保序，最多 20 条
        seen, out = set(), []
        for ln in kept:
            if ln not in seen:
                seen.add(ln)
                out.append(ln)
        return "\n".join(out[:20])
    # 兜底：截取不含路径的行
    fallback = [ln for ln in lines if "error:" in ln and "D:/" not in ln and "C:/" not in ln]
    if fallback:
        return "\n".join(fallback[:20])
    return "编译失败（详见评测日志）"


def _classify(run_res: RunResult, expected: str) -> tuple[str, str]:
    """根据运行结果判定测试点状态。返回 (result, actual_output)。"""
    if run_res.timed_out:
        return "TLE", run_res.stdout
    if run_res.memory_exceeded:
        return "MLE", run_res.stdout
    if run_res.returncode != 0:
        return "RE", run_res.stdout
    if run_res.error:
        return "UNK", run_res.stdout
    if compare_output(run_res.stdout, expected):
        return "AC", run_res.stdout
    return "WA", run_res.stdout
