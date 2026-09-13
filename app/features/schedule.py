"""定时播报（报时/在看人数/自定义）+ 动态文案轮播。

由 pipeline 启动为后台任务，周期性把播报文本入队朗读。
"""
import asyncio
import logging
import random
import time
from datetime import datetime
from pathlib import Path

from ..config import CONFIG, ROOT

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, enqueue_broadcast, get_viewer_count, llm_rewrite):
        self.enqueue_broadcast = enqueue_broadcast      # async (text, kind) -> None
        self.get_viewer_count = get_viewer_count        # async () -> int
        self.llm_rewrite = llm_rewrite                  # async (text) -> str | None
        self._last: dict[str, float] = {}
        self._task: asyncio.Task | None = None

    async def start(self):
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run(self):
        tick = CONFIG["schedule"].get("tick_interval", 30)
        logger.info("定时播报已启动，检查周期 %ss", tick)
        while True:
            try:
                await asyncio.sleep(tick)
                for item in CONFIG["schedule"].get("items", []):
                    if item.get("enable", True):
                        await self._maybe_broadcast(item, "schedule")
                trends = CONFIG["trends"]
                if trends.get("enable"):
                    await self._maybe_broadcast(trends, "trends")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("定时播报异常")

    async def _maybe_broadcast(self, item: dict, kind: str):
        key = f"{kind}:{item.get('type', 'trends')}:{id(item)}"
        interval = float(item.get("interval", 300))
        # 支持 interval_range: [最小, 最大]，每次触发后随机取下一段隔
        rng = item.get("interval_range")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            interval = random.uniform(float(rng[0]), float(rng[1]))
        last = self._last.get(key)
        if last and time.monotonic() - last < interval:
            return
        self._last[key] = time.monotonic()

        text = self._render(item)
        if item.get("type") == "viewers":
            user_num = await self.get_viewer_count()
            text = text.replace("{user_num}", str(user_num)) if text else text
        if kind == "trends":
            text = self._pick_trend(item)
            if not text:
                return
            if item.get("llm_rewrite") and item.get("prompt_change_enable"):
                rewritten = await self.llm_rewrite(
                    item.get("prompt_change_content", "") + text
                )
                if rewritten:
                    text = rewritten
        if text:
            await self.enqueue_broadcast(text, kind)

    def _render(self, item: dict) -> str | None:
        templates = item.get("templates") or []
        if not templates:
            return None
        template = random.choice(templates)
        if item.get("type") == "time":
            return template.replace("{time}", datetime.now().strftime("%H点%M分"))
        if item.get("type") == "viewers":
            return template  # {user_num} 由 pipeline.render_viewers 处理
        return template

    def _pick_trend(self, cfg: dict) -> str | None:
        folder = ROOT / cfg["folder"]
        if not folder.exists():
            return None
        files = [p for p in folder.iterdir() if p.suffix.lower() == ".txt"]
        if not files:
            return None
        lines = []
        for f in files:
            lines += [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return random.choice(lines) if lines else None
