"""TTS 引擎调度：按 config tts.engine 选择引擎，GPT-SoVITS 失败自动回退 edge-tts。

带熔断：连续失败达到阈值后进入冷却期（快速返回 None，不再阻塞播出队列）。
带硬超时：edge-tts 网络挂起时会无限等待，单队列会被卡死，必须限时。
synthesize 返回 Path 或 None（失败/熔断）。
"""
import asyncio
import logging
import time
from pathlib import Path

from ..config import CONFIG
from . import edge, gptsovits

logger = logging.getLogger(__name__)

# 合成缓存目录最多保留的文件数，防止直播跑一天撑爆磁盘
MAX_CACHE_FILES = 300
# 熔断参数：连续失败 N 次进入冷却，冷却期内直接跳过合成
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN = 60.0
# 单次合成硬超时（秒）
SYNTH_TIMEOUT = 20.0

_fail_streak = 0
_cooldown_until = 0.0


def _prune_cache():
    out_dir = CONFIG["tts"]["out_dir"]
    cache_dir = Path(out_dir)
    if not cache_dir.is_absolute():
        from ..config import ROOT
        cache_dir = ROOT / out_dir
    if not cache_dir.exists():
        return
    files = sorted(cache_dir.glob("*"), key=lambda p: p.stat().st_mtime)
    for p in files[:-MAX_CACHE_FILES] if len(files) > MAX_CACHE_FILES else []:
        try:
            p.unlink()
        except OSError:
            pass


async def synthesize(text: str) -> Path | None:
    """合成语音。返回音频文件路径；失败或熔断中返回 None（调用方应降级为纯文字）。"""
    global _fail_streak, _cooldown_until

    if _fail_streak >= BREAKER_THRESHOLD and time.monotonic() < _cooldown_until:
        return None
    if _fail_streak >= BREAKER_THRESHOLD:
        # 冷却期已过，放行一次试探
        _fail_streak = BREAKER_THRESHOLD - 1

    engine = CONFIG["tts"].get("engine", "edge")
    path: Path | None = None
    try:
        if engine == "gptsovits":
            try:
                path = await asyncio.wait_for(gptsovits.synthesize(text), timeout=SYNTH_TIMEOUT)
            except Exception:
                logger.exception("GPT-SoVITS 合成失败，回退 edge-tts")
        if path is None:
            path = await asyncio.wait_for(edge.synthesize(text), timeout=SYNTH_TIMEOUT)
        _fail_streak = 0
        _prune_cache()
        return path
    except Exception:
        _fail_streak += 1
        if _fail_streak >= BREAKER_THRESHOLD:
            _cooldown_until = time.monotonic() + BREAKER_COOLDOWN
            logger.error("TTS 连续失败 %s 次，熔断 %s 秒（期间只发文字不发音）",
                         _fail_streak, BREAKER_COOLDOWN)
        return None
