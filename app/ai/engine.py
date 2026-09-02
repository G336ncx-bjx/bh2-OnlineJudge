"""AI 命题任务执行引擎。

任务状态机：pending -> running -> completed / cancelled / failed
进度通过任务 JSON 的 progress 字段更新，前端轮询读取。
中断通过任务 JSON 的 status 字段置为 cancelled，执行循环检查。
"""
import asyncio
import json
from typing import Optional

from .. import config, storage
from . import llm

# 命题系统提示词：引导模型输出完整题目 JSON
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
  "testcases": [{"input": "测试输入", "output": "测试输出"}],
  "hint": "提示（可选）",
  "source": "来源（可选）",
  "tags": ["标签"],
  "time_limit": 1.0,
  "memory_limit": 128,
  "difficulty": "难度"
}

要求：
1. 测试用例（testcases）必须覆盖边界条件，包括：最小/最大输入、普通情况、特殊情况（如空输入、负数、极值等），至少 5 个测试点。
2. 数据规模要能区分不同时间复杂度的算法（如 O(n) vs O(n^2)）。
3. 题目必须紧扣用户指定的知识点和难度。
4. samples 与 testcases 的输入输出必须严格一致、可验证。
"""


def _get_task(task_id: str) -> Optional[dict]:
    path = config.AI_TASKS_DIR + "/" + task_id + ".json"
    return storage._read_json(path, None)


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
        # 阶段 1：生成题目
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

        # 阶段 3：校验并补全字段
        if await _check_cancelled(task_id):
            return
        task["progress"] = "正在校验并生成测试点"
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


def start_task(task_id: str) -> None:
    """在事件循环中启动命题任务协程。"""
    asyncio.create_task(run_problem_task(task_id))
