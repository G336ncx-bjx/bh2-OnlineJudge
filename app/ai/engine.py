"""AI 命题任务执行引擎。

任务状态机：pending -> running -> completed / cancelled / failed
进度通过任务 JSON 的 progress 字段更新，前端轮询读取。
中断通过任务 JSON 的 status 字段置为 cancelled，执行循环检查。
"""
import asyncio
import json
import os
from typing import Optional

from .. import config, storage
from . import llm

# 命题系统提示词（阶段一）：只生成题目主体，不含 testcases（测试点由阶段二单独生成）
SYSTEM_PROMPT = """你是一名资深的 OJ（在线评测）出题人。请根据用户的命题需求，设计一道完整的编程题。

你必须输出一个合法的 JSON 对象，不要包含任何额外文字，字段如下：
{
  "id": "题目唯一标识（英文+数字，如 sum_3_numbers）",
  "title": "题目标题",
  "description": "题目描述（背景+要求）",
  "input_description": "输入格式说明",
  "output_description": "输出格式说明",
  "samples": [{"input": "样例输入", "output": "样例输出"}],
  "constraints": "数据范围与限制",
  "hint": "提示（可选）",
  "source": "来源（可选）",
  "tags": ["标签"],
  "time_limit": 1.0,
  "memory_limit": 128,
  "difficulty": "难度"
}

要求：
1. 题目必须紧扣用户指定的知识点和难度。
2. 数据规模要能区分不同时间复杂度的算法（如 O(n) vs O(n^2)），并写清楚在 constraints 中。
3. 样例（samples）至少 2 组，输入输出必须严格一致、可验证。
4. 只输出上述字段，不要包含 testcases（测试点会另行生成）。
"""

# 命题系统提示词（阶段二）：只生成测试点
TESTCASE_PROMPT = """你是 OJ 测试点设计专家。下面是一道已设计好的编程题，请为它生成测试用例（testcases）。

题目信息：
{problem}

你必须输出一个合法的 JSON 对象，不要包含任何额外文字，字段如下：
{{
  "testcases": [{{"input": "测试输入", "output": "测试输出"}}]
}}

要求：
1. 测试用例必须覆盖边界条件：最小规模、最大规模、普通情况、特殊情况（如空输入、负数、极值、单元素等）。
2. 至少 5 个测试点，且要能卡掉常见的错误解法（如暴力算法、错误的贪心）。
3. 每个测试点的 input 必须是完整、可直接运行的输入（不允许省略、不允许写「略」或占位符）。
4. 每个测试点的 output 必须是与 input 严格对应的正确输出。
5. 输入输出格式必须严格符合题目的 input_description / output_description。
"""


def _get_task(task_id: str) -> Optional[dict]:
    path = config.AI_TASKS_DIR + "/" + task_id + ".json"
    return storage._read_json(path, None)


def list_task_ids() -> list[str]:
    """返回所有 AI 命题任务 id（按文件名排序）。"""
    if not os.path.isdir(config.AI_TASKS_DIR):
        return []
    ids = [
        f[:-5] for f in os.listdir(config.AI_TASKS_DIR) if f.endswith(".json")
    ]
    return sorted(ids)


def _save_task(task: dict) -> None:
    path = config.AI_TASKS_DIR + "/" + task["task_id"] + ".json"
    storage._write_json(path, task)


def _new_task(task_id: str, requirement: str, user_id: str,
              problem_id: Optional[str]) -> dict:
    cfg = llm.get_model_config_raw()
    return {
        "task_id": task_id,
        "user_id": user_id,
        "requirement": requirement,
        "problem_id": problem_id,
        "status": "pending",
        "progress": "任务已创建，等待执行",
        "created_time": storage.now_str(),
        "result": None,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
            "currency": cfg.get("currency", "USD"),
        },
    }


def _accumulate_usage(task: dict, usage: dict) -> None:
    """累计 token 用量并计算费用。"""
    if not usage:
        return
    u = task["usage"]
    u["input_tokens"] = u.get("input_tokens", 0) + usage.get("input_tokens", 0)
    u["output_tokens"] = u.get("output_tokens", 0) + usage.get("output_tokens", 0)
    u["total_tokens"] = u.get("total_tokens", 0) + usage.get("total_tokens", 0)
    cfg = llm.get_model_config_raw()
    u["cost"] = llm.calc_cost({
        "input_tokens": u["input_tokens"],
        "output_tokens": u["output_tokens"],
        "total_tokens": u["total_tokens"],
    }, cfg)
    u["currency"] = cfg.get("currency", "USD")


def _build_requirement_prompt(task: dict) -> str:
    """构造用户命题需求 prompt，含知识点、难度、参考题目等。"""
    parts = ["请根据以下需求设计一道 OJ 题目：", task["requirement"]]
    if task.get("problem_id"):
        ref = storage.get_problem(task["problem_id"])
        if ref:
            parts.append(
                f"\n\n可参考以下已有题目的背景（可改编，也可全新设计）：\n"
                f"标题：{ref.get('title', '')}\n"
                f"描述：{ref.get('description', '')}\n"
                f"输入说明：{ref.get('input_description', '')}\n"
                f"输出说明：{ref.get('output_description', '')}"
            )
    return "\n".join(parts)


async def _check_cancelled(task_id: str) -> bool:
    """检查任务是否已被取消。"""
    await asyncio.sleep(0)  # 让出事件循环
    task = _get_task(task_id)
    return task is not None and task.get("status") == "cancelled"


async def run_problem_task(task_id: str) -> None:
    """执行命题任务（在后台协程中运行）。"""
    task = _get_task(task_id)
    if task is None:
        return

    task["status"] = "running"
    task["progress"] = "正在分析命题需求"
    _save_task(task)

    try:
        # 阶段 1：生成题目主体（不含 testcases，控制单次输出长度）
        if await _check_cancelled(task_id):
            return
        task["progress"] = "正在设计题目内容"
        _save_task(task)

        prompt = _build_requirement_prompt(task)
        content, usage = await llm.call_llm([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        _accumulate_usage(task, usage)

        # 阶段 2：解析题目 JSON
        if await _check_cancelled(task_id):
            return
        task["progress"] = "正在解析题目配置"
        _save_task(task)

        problem = llm.parse_problem_json(content)
        if problem is None:
            task["status"] = "failed"
            task["progress"] = "模型返回内容无法解析为题目 JSON"
            task["error_info"] = "模型返回内容无法解析为题目 JSON"
            _save_task(task)
            return

        # 阶段 3：生成测试点（单独一次调用，避免整题过长被截断）
        if await _check_cancelled(task_id):
            return
        task["progress"] = "正在生成测试点"
        _save_task(task)

        testcases = await _generate_testcases(task, problem)
        if testcases is None:
            task["status"] = "failed"
            task["progress"] = "测试点生成失败"
            task["error_info"] = "测试点生成失败：模型返回内容无法解析"
            _save_task(task)
            return
        problem["testcases"] = testcases

        # 阶段 4：校验并补全字段
        if await _check_cancelled(task_id):
            return
        task["progress"] = "正在校验题目配置"
        _save_task(task)

        problem = _normalize_problem(problem)
        if problem is None:
            task["status"] = "failed"
            task["progress"] = "生成的题目缺少必填字段"
            task["error_info"] = "生成的题目缺少必填字段"
            _save_task(task)
            return

        # 完成
        task["status"] = "completed"
        task["progress"] = "命题完成"
        task["result"] = problem
        _save_task(task)

    except asyncio.CancelledError:
        task["status"] = "cancelled"
        task["progress"] = "任务已中断"
        _save_task(task)
        raise
    except Exception as e:
        task["status"] = "failed"
        task["progress"] = f"命题失败: {type(e).__name__}"
        task["error_info"] = f"命题出错: {e}"
        _save_task(task)


async def _generate_testcases(task: dict, problem: dict) -> Optional[list]:
    """阶段二：单独调用模型为题目生成测试点，返回 testcases 列表（失败返回 None）。

    把题目主体序列化成精简 JSON 作为上下文传给模型，让模型只输出测试点，
    避免「整题+测试点」一次性输出过长导致被 max_tokens 截断。
    """
    summary = {
        "title": problem.get("title", ""),
        "description": problem.get("description", ""),
        "input_description": problem.get("input_description", ""),
        "output_description": problem.get("output_description", ""),
        "samples": problem.get("samples", []),
        "constraints": problem.get("constraints", ""),
    }
    problem_text = json.dumps(summary, ensure_ascii=False, indent=2)

    content, usage = await llm.call_llm([
        {"role": "system", "content": TESTCASE_PROMPT.format(problem=problem_text)},
        {"role": "user", "content": "请为上述题目生成测试点。"},
    ])
    _accumulate_usage(task, usage)

    parsed = llm.parse_problem_json(content)
    if not parsed or not isinstance(parsed.get("testcases"), list):
        return None
    testcases = parsed["testcases"]
    if not testcases:
        return None
    return testcases


def _normalize_problem(problem: dict) -> Optional[dict]:
    """校验并规范化题目字段，确保满足 Step1 要求。"""
    required = ["id", "title", "description", "input_description",
                "output_description", "samples", "constraints", "testcases"]
    for field in required:
        if field not in problem or problem[field] in (None, ""):
            return None
    if not isinstance(problem["samples"], list) or not problem["samples"]:
        return None
    if not isinstance(problem["testcases"], list) or not problem["testcases"]:
        return None
    # 规范化可选字段
    problem.setdefault("hint", "")
    problem.setdefault("source", "")
    problem.setdefault("tags", [])
    problem.setdefault("time_limit", 3.0)
    problem.setdefault("memory_limit", 128)
    problem.setdefault("author", "")
    problem.setdefault("difficulty", "")
    problem.setdefault("public_cases", False)
    # 确保 samples/testcases 元素结构正确
    for s in problem["samples"]:
        if not isinstance(s, dict) or "input" not in s or "output" not in s:
            return None
    for t in problem["testcases"]:
        if not isinstance(t, dict) or "input" not in t or "output" not in t:
            return None
    return problem


# 全局运行中的任务协程注册表：task_id -> asyncio.Task
# 用于「真正终止」——中断时直接取消协程，打断正在进行的 LLM HTTP 调用。
_RUNNING_TASKS: dict[str, "asyncio.Task"] = {}


def start_task(task_id: str) -> None:
    """在事件循环中启动命题任务协程，并登记以便中断时真正取消。"""
    coro = run_problem_task(task_id)
    t = asyncio.create_task(coro)
    _RUNNING_TASKS[task_id] = t
    # 任务结束后自动从注册表移除
    t.add_done_callback(lambda _: _RUNNING_TASKS.pop(task_id, None))


def cancel_task(task_id: str) -> bool:
    """真正取消运行中的命题任务协程，打断正在进行的 LLM 调用。

    返回 True 表示存在运行中的协程并已发起取消；False 表示协程已结束。
    """
    t = _RUNNING_TASKS.get(task_id)
    if t is None:
        return False
    t.cancel()
    return True
