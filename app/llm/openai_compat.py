"""OpenAI 兼容接口的对话客户端（DeepSeek / GLM / Qwen / OpenAI 均可用）。

未配置 api_key 时返回 None，由上层走兜底回复，保证 demo 离线也能跑。
支持传入历史消息实现多轮上下文。
"""
import logging

import httpx

from ..config import CONFIG

logger = logging.getLogger(__name__)


async def _call(system: str, messages: list[dict], max_tokens: int | None = None) -> str | None:
    cfg = CONFIG["llm"]
    if not cfg.get("enabled") or not cfg.get("api_key"):
        return None

    payload = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system}, *messages],
        "max_tokens": max_tokens or cfg.get("max_tokens", 120),
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{cfg['base_url'].rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.exception("LLM 调用失败")
        return None


async def chat(user_text: str, history: list[dict] | None = None) -> str | None:
    cfg = CONFIG["llm"]
    messages = [*(history or []), {"role": "user", "content": user_text}]
    return await _call(cfg["system_prompt"], messages)


async def rewrite(prompt: str) -> str | None:
    """动态文案改写等辅助用途。"""
    return await _call(
        "你是直播文案改写助手。根据用户输入的内容，意思不变、表达不同，直接输出新文案，不要任何解释。",
        [{"role": "user", "content": prompt}],
    )
