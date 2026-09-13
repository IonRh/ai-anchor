"""GPT-SoVITS api_v2 客户端。

需要本地/远程跑起 GPT-SoVITS 的 api_v2 服务（python api_v2.py -a 0.0.0.0 -p 9880），
config.json 的 tts.gptsovits 里配置参考音频等参数。
"""
import logging
import uuid
from pathlib import Path

import httpx

from ..config import CONFIG, ROOT

logger = logging.getLogger(__name__)


async def synthesize(text: str) -> Path:
    cfg = CONFIG["tts"]["gptsovits"]
    out_dir = ROOT / CONFIG["tts"]["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    params = {
        "text": text,
        "text_lang": cfg.get("text_lang", "zh"),
        "ref_audio_path": cfg["ref_audio_path"],
        "prompt_text": cfg.get("prompt_text", ""),
        "prompt_lang": cfg.get("prompt_lang", "zh"),
        "speed_factor": cfg.get("speed_factor", 1.0),
        "media_type": cfg.get("media_type", "wav"),
        "streaming_mode": "false",
    }
    url = f"{cfg['api_ip_port'].rstrip('/')}/tts"

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        if not resp.content:
            raise RuntimeError("GPT-SoVITS 返回空音频")

    out_path = out_dir / f"{uuid.uuid4().hex}.{cfg.get('media_type', 'wav')}"
    out_path.write_bytes(resp.content)
    return out_path
