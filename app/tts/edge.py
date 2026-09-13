"""edge-tts 封装：文本 → mp3 文件，返回文件路径。

微软接口偶发 NoAudioReceived，做最多 3 次重试。
"""
import asyncio
import logging
import uuid
from pathlib import Path

import edge_tts

from ..config import CONFIG, ROOT

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


async def synthesize(text: str) -> Path:
    cfg = CONFIG["tts"]
    out_dir = ROOT / cfg["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{uuid.uuid4().hex}.mp3"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            communicate = edge_tts.Communicate(
                text, cfg["voice"], rate=cfg["rate"], volume=cfg["volume"]
            )
            await communicate.save(str(out_path))
            return out_path
        except edge_tts.exceptions.NoAudioReceived:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("TTS 第 %s 次失败（NoAudioReceived），重试", attempt)
            await asyncio.sleep(1.5 * attempt)
    raise RuntimeError("unreachable")
