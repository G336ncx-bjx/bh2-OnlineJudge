"""AI 模型配置管理与 LLM 调用。

配置通过 OpenAI 兼容的 chat completions 接口调用任意模型提供商。
"""
import asyncio
import json
from typing import Optional

import httpx

from .. import config, storage


# ---------------------------------------------------------------- 模型配置
def get_model_config() -> dict:
    """读取模型配置（不含明文密钥）。"""
    cfg = storage._read_json(config.AI_MODEL_CONFIG_FILE, {})
    return {
        "provider_url": cfg.get("provider_url", ""),
        "model": cfg.get("model", ""),
        "api_key_configured": bool(cfg.get("api_key")),
        "input_price": cfg.get("input_price", 0.0),
        "output_price": cfg.get("output_price", 0.0),
        "price_unit": cfg.get("price_unit", 1000000),
        "currency": cfg.get("currency", "USD"),
        "max_tokens": cfg.get("max_tokens", config.AI_MAX_TOKENS),
    }


def get_model_config_raw() -> dict:
    """读取完整模型配置（含密钥，仅内部使用）。"""
    return storage._read_json(config.AI_MODEL_CONFIG_FILE, {})


def save_model_config(cfg: dict) -> None:
    storage._write_json(config.AI_MODEL_CONFIG_FILE, cfg)


# ---------------------------------------------------------------- LLM 调用
async def call_llm(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    timeout: float = None,
) -> tuple[str, dict]:
    """调用模型，返回 (content, usage)。

    usage 形如 {"input_tokens": int, "output_tokens": int, "total_tokens": int}
    模型接口不提供用量时返回空 dict。

    max_tokens 默认取模型配置中的 max_tokens 字段，未配置则用
    config.AI_MAX_TOKENS（32768）。复杂题题目主体输出较长，16384 曾被截断
    导致 JSON 解析失败，故默认放宽；如需更大可在模型配置中自定义。

    timeout 同时作为 httpx 内部超时与外层 asyncio.wait_for 的硬截止时间；
    默认取 config.AI_LLM_TIMEOUT（命题生成耗时较长，放宽到 10 分钟）。
    之所以加外层 wait_for：DeepSeek 等 provider 在并发下可能采用流式响应，
    一旦响应读到一半挂起，httpx 的读超时会在每次收到数据块时被重置而失效，
    导致协程永久挂起。外层 wait_for 提供不依赖底层行为的强制兜底。
    """
    if timeout is None:
        timeout = config.AI_LLM_TIMEOUT

    cfg = get_model_config_raw()
    provider_url = cfg.get("provider_url", "")
    model = cfg.get("model", "")
    api_key = cfg.get("api_key", "")

    if max_tokens is None:
        max_tokens = cfg.get("max_tokens", config.AI_MAX_TOKENS) or config.AI_MAX_TOKENS

    if not provider_url or not model:
        raise RuntimeError("模型未配置：请先设置 provider_url 和 model")

    # 拼接 chat completions 端点
    url = provider_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url + "/chat/completions"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    async def _post() -> dict:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    # 连接类瞬时故障自动重试（如 SSL 握手/记录层失败、连接被重置等网络抖动）。
    # 这类错误请求未送达模型（不产生费用），重试通常即可成功。
    # 注意：不重试 HTTP 业务状态码错误（HTTPStatusError）与超时（外层 wait_for）。
    last_err: Optional[Exception] = None
    for attempt in range(config.AI_LLM_MAX_RETRIES + 1):
        try:
            # 外层硬超时兜底：即使 httpx 内部超时被流式响应重置，也强制在 timeout 内返回
            data = await asyncio.wait_for(_post(), timeout=timeout)
            break
        except asyncio.TimeoutError:
            raise
        except asyncio.CancelledError:
            raise
        except httpx.HTTPStatusError:
            raise
        except (httpx.HTTPError, OSError) as e:
            # OSError 覆盖 ssl.SSLError（如 DECRYPTION_FAILED_OR_BAD_RECORD_MAC）、
            # ConnectionResetError 等未经过 httpx 包装直接抛出的系统级网络错误。
            last_err = e
            if attempt >= config.AI_LLM_MAX_RETRIES:
                raise
            await asyncio.sleep(config.AI_LLM_RETRY_DELAY * (attempt + 1))
    else:
        raise last_err

    content = data["choices"][0]["message"]["content"]

    usage = {}
    u = data.get("usage")
    if u:
        usage = {
            "input_tokens": u.get("prompt_tokens", 0),
            "output_tokens": u.get("completion_tokens", 0),
            "total_tokens": u.get("total_tokens", 0),
        }
    return content, usage


def calc_cost(usage: dict, cfg: dict) -> float:
    """根据用量和价格计算费用。

    费用 = 输入 Token / price_unit * input_price
         + 输出 Token / price_unit * output_price
    """
    if not usage:
        return 0.0
    price_unit = cfg.get("price_unit", 1000000) or 1000000
    input_price = cfg.get("input_price", 0.0) or 0.0
    output_price = cfg.get("output_price", 0.0) or 0.0
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cost = (input_tokens / price_unit * input_price) + (output_tokens / price_unit * output_price)
    return round(cost, 6)


def parse_problem_json(text: str) -> Optional[dict]:
    """从模型返回文本中提取题目 JSON。

    兼容 ```json ... ``` 代码块包裹或纯 JSON 的情况；
    对因 max_tokens 截断而残缺的 JSON 做兜底修复（截到最后一个完整字段）。
    """
    text = text.strip()
    # 去掉代码块标记
    if text.startswith("```"):
        lines = text.split("\n")
        # 去掉首行 ```json 和末行 ```
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试找第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        # 兜底：max_tokens 截断导致尾部残缺，截到最后一个完整的顶层键值对
        return _repair_truncated_json(text, start)


def _repair_truncated_json(text: str, start: int) -> Optional[dict]:
    """尝试修复被截断的 JSON，返回解析出的 dict 或 None。

    分阶段尝试多种修复策略，从「最保守（丢弃最少的字段）」到「更激进」：
    1. 顶层逗号截断：在最后一个「字符串外、深度为 1」的逗号处截断补 '}'；
    2. 直接补闭合：把末尾未闭合的 '['/'{' 逐个补上 ']'/'}' 再解析；
    3. 顶层字段逐个回退：逐步丢弃最后一个字段再补 '}'。
    """
    if start == -1:
        return None
    tail = text[start:]

    # 策略 1：顶层逗号截断（最保守，保留最多完整字段）
    # tail 以最外层 '{' 开头，其顶层字段逗号在 depth == 1 这一层
    commas = []
    in_string = False
    escape = False
    depth = 0
    for i, ch in enumerate(tail):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "," and depth == 1:
            commas.append(i)
    for cut in reversed(commas):
        fixed = tail[:cut] + "}"
        try:
            obj = json.loads(fixed)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    # 策略 2：直接补闭合缺失的括号
    # 扫描出字符串外仍未闭合的 '[' 和 '{'，按逆序补 ']'/'}'
    stack = []
    in_string = False
    escape = False
    for ch in tail:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            stack.append(ch)
        elif ch in "]}":
            if stack:
                stack.pop()
    closes = []
    for opener in reversed(stack):
        closes.append("]" if opener == "[" else "}")
    fixed = tail + "".join(closes)
    try:
        obj = json.loads(fixed)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 策略 3：逐步丢弃末尾未完成的字段（逐字符向前回退，补 '}' 试解析）
    # 从末尾向前，逐个尝试在「字符串外、深度为 1」的 ':' 或 ',' 处截断
    for cut in range(len(tail) - 1, 0, -1):
        ch = tail[cut]
        if ch not in (":", ","):
            continue
        fixed = tail[:cut] + "}"
        try:
            obj = json.loads(fixed)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None
