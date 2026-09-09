"""AI 命题任务执行引擎。

任务状态机：pending -> running -> completed / cancelled / failed
进度通过任务 JSON 的 progress 字段更新，前端轮询读取。
中断通过任务 JSON 的 status 字段置为 cancelled，执行循环检查。
"""
import asyncio
import json
import os
import re
from typing import Optional

from .. import config, storage
from ..judge.runner import run_command
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

# 命题系统提示词（阶段二）：只生成测试点（分批，每次指定数量，降低单次输出长度）
TESTCASE_PROMPT = """你是 OJ 测试点设计专家。下面是一道已设计好的编程题，请为它生成测试用例（testcases）。

题目信息：
{problem}

{quantity_hint}

你必须输出一个合法的 JSON 对象，不要包含任何额外文字，字段如下：
{{
  "testcases": [{{"input": "测试输入", "output": "测试输出"}}]
}}

要求：
1. 本次只需生成指定数量的测试点，不要贪多，务必精简，每个测试点的 input/output 尽量简短。
2. 每个测试点的 input 必须是完整、可直接运行的输入（不允许省略、不允许写「略」或占位符）。
3. 每个测试点的 output 必须是与 input 严格对应的正确输出。
4. 输入输出格式必须严格符合题目的 input_description / output_description。
5. {coverage}
"""

# 阶段三：大测试点生成器提示词。
# 直接让模型输出大规模测试数据不现实（输出 token 上限），改为让模型写一个
# 「数据生成器 + 标程」Python 脚本，由服务器本地执行产出大规模输入和标准输出，
# 从而突破模型输出长度限制，并满足 4 分钟内出题的时间要求。
GENERATOR_PROMPT = """你是 OJ 测试点生成器设计专家。下面这道题在 constraints 中声明了较大规模的数据，但已生成的测试点规模偏小，需要补充大规模测试点。

题目信息：
{problem}

请输出一个 Python 脚本（不要用 markdown 代码块包裹，直接输出纯代码），脚本必须：
1. 定义函数 generate_input() -> str：返回一个符合 input_description 的**大规模**输入字符串（数据规模逼近 constraints 上限，如 n 取最大值、行数上万等）。
2. 定义函数 solve(data: str) -> str：返回该输入对应的正确输出字符串。solve 使用能通过题目的正确算法（标程），例如数据规模大时用 O(n log n) 或更优的解法。
3. 在脚本末尾包含：
   data = generate_input()
   print("===INPUT===")
   print(data, end="")
   print("===OUTPUT===")
   print(solve(data), end="")
4. 脚本只依赖 Python 标准库，不要导入第三方库。
5. 保证 generate_input 生成的数据满足 constraints 中的全部范围限制。
6. 保证 solve 的输出格式严格符合 output_description。
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

        # 阶段 3.5：大规模测试点增强（可选，失败不影响整体）
        # constraints 声明大规模数据但已生成测试点规模偏小时，让模型写
        # 「生成器+标程」脚本，本地执行产出大规模测试点，突破模型输出上限。
        if await _check_cancelled(task_id):
            return
        if _needs_large_testcases(problem):
            task["progress"] = "正在生成大规模测试点"
            _save_task(task)
            large = await _generate_large_testcases(task, problem)
            if large:
                problem["testcases"].extend(large)

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
        # 注意：asyncio.TimeoutError 的 str() 为空串，直接 f"{e}" 会导致 error_info 空白，
        # 故用 type(e).__name__ 兜底，并单独识别超时给出可读提示。
        name = type(e).__name__
        if name == "TimeoutError":
            hint = "模型响应超时，请稍后重试或降低题目复杂度"
        else:
            hint = str(e) or name
        task["status"] = "failed"
        task["progress"] = f"命题失败: {name}"
        task["error_info"] = f"命题出错: {hint}"
        _save_task(task)


async def _generate_testcases(task: dict, problem: dict) -> Optional[list]:
    """阶段二：分批调用模型为题目生成测试点，返回 testcases 列表（失败返回 None）。

    把题目主体序列化成精简 JSON 作为上下文传给模型，让模型只输出测试点，
    避免「整题+测试点」一次性输出过长导致被 max_tokens 截断或触发硬超时。

    分批生成：每次只让模型生成少量测试点（BATCH_SIZE 个），循环凑够至少
    MIN_CASES 个。这样单次输出短、耗时短、进度可见；单批失败可重试而不整体失败，
    从根本上降低「复杂题生成测试点超时」的概率。
    """
    MIN_CASES = 5      # 至少生成 5 个测试点
    BATCH_SIZE = 3     # 每批生成 3 个（首尾各补一点冗余以覆盖边界）
    MAX_BATCHES = 4    # 最多 4 批（兜底，防止无限循环）

    summary = {
        "title": problem.get("title", ""),
        "description": problem.get("description", ""),
        "input_description": problem.get("input_description", ""),
        "output_description": problem.get("output_description", ""),
        "samples": problem.get("samples", []),
        "constraints": problem.get("constraints", ""),
    }
    problem_text = json.dumps(summary, ensure_ascii=False, indent=2)

    # 按批次分配不同的覆盖侧重，保证整体覆盖边界/普通/特殊情况
    coverage_plan = [
        "重点覆盖普通情况与最小规模的边界情况。",
        "重点覆盖最大规模、极值与特殊输入（如空输入、负数、单元素等）。",
        "补充能卡掉常见错误解法（暴力、错误贪心等）的用例。",
        "继续补充遗漏的边界与特殊用例。",
    ]

    collected: list = []
    for batch_idx in range(MAX_BATCHES):
        if len(collected) >= MIN_CASES:
            break

        remaining = MIN_CASES - len(collected)
        want = min(BATCH_SIZE, remaining)
        coverage = coverage_plan[batch_idx % len(coverage_plan)]
        quantity_hint = f"本次请生成 {want} 个测试点。"
        system = TESTCASE_PROMPT.format(
            problem=problem_text, quantity_hint=quantity_hint, coverage=coverage
        )

        # 单批失败重试一次（引导更精简输出）
        parsed = None
        user_hint = f"请为上述题目生成 {want} 个测试点。"
        for attempt in range(2):
            content, usage = await llm.call_llm([
                {"role": "system", "content": system},
                {"role": "user", "content": user_hint},
            ])
            _accumulate_usage(task, usage)

            parsed = llm.parse_problem_json(content)
            if parsed and isinstance(parsed.get("testcases"), list) and parsed["testcases"]:
                break
            user_hint = (
                f"请为上述题目生成 {want} 个测试点。注意：只需输出 testcases 列表，"
                "务必精简，每个测试点的 input/output 尽量简短。"
            )

        if not parsed or not isinstance(parsed.get("testcases"), list):
            # 本批两次都失败：若已有部分测试点则返回已收集的，否则继续下一批
            continue

        for tc in parsed["testcases"]:
            if isinstance(tc, dict) and "input" in tc and "output" in tc:
                collected.append(tc)

    return collected if collected else None


# ---------------------------------------------------------------- 大规模测试点
def _needs_large_testcases(problem: dict) -> bool:
    """判断是否需要补充大规模测试点。

    启发式：从 constraints 中提取声明的大数据量（如 n、长度、范围上限），
    若声明的规模（≥10^4 量级）明显大于已有测试点的实际输入规模，则认为需要。
    保守策略：拿不准时返回 False（不折腾，保持流程稳定）。
    """
    constraints = problem.get("constraints", "") or ""
    tcs = problem.get("testcases", [])
    if not tcs:
        return False
    max_in_len = max(len(tc.get("input", "")) for tc in tcs)
    # 提取 constraints 中的数字上限（取最大的数值）
    nums = [int(x) for x in re.findall(r"\d+", constraints)]
    big = [n for n in nums if n >= 10_000]
    if not big:
        return False
    declared_max = max(big)
    # 实际输入太小（字符数 < 声明规模的 1/100，且小于 2000 字符）才需要增强
    if max_in_len < 2000 and max_in_len * 100 < declared_max:
        return True
    return False


def _extract_code(content: str) -> str:
    """从模型返回文本中提取脚本代码（兼容 markdown 代码块）。"""
    text = content.strip()
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


async def _generate_large_testcases(task: dict, problem: dict) -> Optional[list]:
    """让模型写「生成器+标程」脚本，本地执行产出大规模测试点。

    返回 testcases 列表（成功）或 None（失败，不影响整体流程）。
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

    try:
        content, usage = await llm.call_llm(
            [
                {"role": "system", "content": GENERATOR_PROMPT.format(problem=problem_text)},
                {"role": "user", "content": "请输出生成器脚本。"},
            ],
            temperature=0.3,
        )
        _accumulate_usage(task, usage)
    except Exception:
        return None
    if await _check_cancelled(task.get("task_id", "")):
        return None

    code = _extract_code(content)
    if "generate_input" not in code or "solve" not in code:
        return None

    # 在临时目录写脚本并执行
    tmp_dir = os.path.join(config.JUDGE_TMP_DIR, "gen_" + task.get("task_id", "x"))
    os.makedirs(tmp_dir, exist_ok=True)
    script_path = os.path.join(tmp_dir, "gen.py")
    try:
        with open(script_path, "w", encoding="utf-8", newline="") as f:
            f.write(code)
        res = await run_command(
            ["python", script_path],
            stdin_data="",
            time_limit=30.0,          # 标程运行 30s 上限
            memory_limit=512.0,       # 512MB
            cwd=tmp_dir,
        )
        if res.timed_out or res.memory_exceeded or res.returncode != 0:
            return None
        out = res.stdout
        # 用固定标记切分（不用正则非贪婪，避免输入数据内部的换行干扰匹配）
        in_marker = "===INPUT==="
        out_marker = "===OUTPUT==="
        i_pos = out.find(in_marker)
        o_pos = out.find(out_marker)
        if i_pos == -1 or o_pos == -1 or o_pos <= i_pos:
            return None
        big_input = out[i_pos + len(in_marker):o_pos]
        big_output = out[o_pos + len(out_marker):]
        # 去掉首尾多余空白（标记后的第一个换行、末尾的换行）
        big_input = big_input.strip("\n")
        big_output = big_output.strip("\n")
        # 数据确实大才有意义
        if len(big_input) < 2000:
            return None
        return [{"input": big_input, "output": big_output}]
    except Exception:
        return None
    finally:
        # 清理临时目录
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


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
