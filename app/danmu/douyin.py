"""抖音弹幕适配器：对接外部「抖音弹幕源」HTTP 服务。

抖音没有官方弹幕 API，本项目采用与原 meng-yun-ai 相同的思路：
由独立弹幕源程序（如原项目的 AIGC_DYDM 弹幕源，或任一开源抖音弹幕抓取服务）
负责抓取，本服务定期轮询其 HTTP 接口。

约定的返回格式（JSON 数组，每项）：
  {"type": "danmu"|"enter"|"gift"|"follow",
   "username": "...",
   "text": "...",          # type=danmu 时
   "gift_name": "...", "gift_num": 1}   # type=gift 时
"""
import asyncio
import logging
from typing import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

EventHandler = Callable[[str, dict], Awaitable[None]]


class DouyinSourceClient:
    def __init__(self, source_url: str, room_id: str, handler: EventHandler):
        self.source_url = source_url
        self.room_id = room_id
        self.handler = handler
        self._task: asyncio.Task | None = None

    async def start(self):
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run(self):
        logged_error = False
        async with httpx.AsyncClient(timeout=5) as client:
            while True:
                try:
                    resp = await client.get(
                        self.source_url, params={"room_id": self.room_id}
                    )
                    resp.raise_for_status()
                    items = resp.json()
                    if not isinstance(items, list):
                        items = [items]
                    for item in items:
                        await self.handler(str(item.get("type") or "danmu"), item)
                    logged_error = False
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if not logged_error:
                        logger.warning("抖音弹幕源 %s 拉取失败：%s（持续失败只记录一次）",
                                       self.source_url, e)
                        logged_error = True
                await asyncio.sleep(2)
