"""AI 模型配置管理与 LLM 调用。

配置通过 OpenAI 兼容的 chat completions 接口调用任意模型提供商。
"""
import json
from typing import Any, Optional

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
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> tuple[str, dict]:
    """调用模型，返回 (content, usage)。

    usage 形如 {"input_tokens": int, "output_tokens": int, "total_tokens": int}
    模型接口不提供用量时返回空 dict。
    """
    cfg = get_model_config_raw()
    provider_url = cfg.get("provider_url", "")
    model = cfg.get("model", "")
    api_key = cfg.get("api_key", "")

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

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

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

    兼容 ```json ... ``` 代码块包裹或纯 JSON 的情况。
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
                return None
        return None
