"""B 站直播间弹幕接入，基于 bilibili-api-python 的 LiveDanmaku。

解析事件：DANMU_MSG 弹幕、INTERACT_WORD 进场、SEND_GIFT 礼物、
USER_TOAST_MSG（action 含"关注"时视为关注）。其余事件忽略。
"""
import logging
from typing import Awaitable, Callable

from bilibili_api import live, Credential

logger = logging.getLogger(__name__)

# handler 类型： DanmuHandler(username, text) / EnterHandler(username)
#               GiftHandler(username, gift_name, num, price_yuan) / FollowHandler(username)
#               LikeHandler(username, count) / FanclubHandler(username)
DanmuHandler = Callable[[str, str], Awaitable[None]]
EnterHandler = Callable[[str], Awaitable[None]]
GiftHandler = Callable[[str, str, int, float], Awaitable[None]]
FollowHandler = Callable[[str], Awaitable[None]]
LikeHandler = Callable[[str, int], Awaitable[None]]
FanclubHandler = Callable[[str], Awaitable[None]]


def _payload(event: dict) -> dict:
    """bilibili-api 可能包裹为 {"data": 原始payload}，也可能直接透传原始 dict。"""
    data = event.get("data")
    if isinstance(data, dict):
        return data
    return event


class BilibiliDanmuClient:
    def __init__(
        self,
        room_id: int,
        sessdata: str = "",
        danmu_handler: DanmuHandler | None = None,
        enter_handler: EnterHandler | None = None,
        gift_handler: GiftHandler | None = None,
        follow_handler: FollowHandler | None = None,
        like_handler: LikeHandler | None = None,
        fanclub_handler: FanclubHandler | None = None,
    ):
        self.room_id = room_id
        self.danmu_handler = danmu_handler
        self.enter_handler = enter_handler
        self.gift_handler = gift_handler
        self.follow_handler = follow_handler
        self.like_handler = like_handler
        self.fanclub_handler = fanclub_handler

        credential = Credential(sessdata=sessdata) if sessdata else None
        self._danmaku = live.LiveDanmaku(room_display_id=room_id, credential=credential)
        self._danmaku.add_event_listener("DANMU_MSG", self._on_danmu)
        self._danmaku.add_event_listener("INTERACT_WORD", self._on_enter)
        self._danmaku.add_event_listener("SEND_GIFT", self._on_gift)
        self._danmaku.add_event_listener("USER_TOAST_MSG", self._on_toast)
        self._danmaku.add_event_listener("LIKE_MSG", self._on_like)
        # 粉丝团事件名在不同版本存在差异，两个名字都注册，未触发也无副作用
        self._danmaku.add_event_listener("FANS_CLUB_MSG", self._on_fanclub)
        self._danmaku.add_event_listener("FAN_CLUB_MSG", self._on_fanclub)

    async def _on_danmu(self, event: dict):
        try:
            info = _payload(event)["info"]
            text = str(info[1])
            username = str(info[2][1])
        except (KeyError, IndexError, TypeError):
            logger.warning("无法解析的 DANMU_MSG: %r", event)
            return
        if self.danmu_handler:
            await self.danmu_handler(username, text)

    async def _on_enter(self, event: dict):
        data = _payload(event)
        username = str(data.get("uname") or "")
        if not username:
            return
        if self.enter_handler:
            await self.enter_handler(username)

    async def _on_gift(self, event: dict):
        data = _payload(event)
        username = str(data.get("uname") or "")
        gift_name = str(data.get("giftName") or "")
        if not username or not gift_name:
            return
        num = int(data.get("num") or 1)
        # price 为金瓜子单价，1000 金瓜子 ≈ 1 元
        price_yuan = float(data.get("price") or 0) * num / 1000.0
        if self.gift_handler:
            await self.gift_handler(username, gift_name, num, price_yuan)

    async def _on_toast(self, event: dict):
        # USER_TOAST_MSG：action 为 "关注"/"特别关注" 时按关注处理，其余（如舰长）忽略
        data = _payload(event)
        action = str(data.get("action") or "")
        if "关注" not in action:
            return
        username = str(data.get("username") or data.get("uname") or "")
        if username and self.follow_handler:
            await self.follow_handler(username)

    async def _on_like(self, event: dict):
        data = _payload(event)
        username = str(data.get("uname") or data.get("username") or "")
        if not username:
            return
        count = int(data.get("like_count") or 1)
        if self.like_handler:
            await self.like_handler(username, count)

    async def _on_fanclub(self, event: dict):
        data = _payload(event)
        username = str(data.get("uname") or data.get("nickname")
                       or data.get("username") or "")
        if username and self.fanclub_handler:
            await self.fanclub_handler(username)

    def danmaku_status(self):
        """透传底层 LiveDanmaku 连接状态（STATUS_ESTABLISHED=2 为已认证）。"""
        return self._danmaku.get_status()

    @property
    def STATUS_ESTABLISHED(self):
        return live.LiveDanmaku.STATUS_ESTABLISHED

    async def connect(self):
        # v17 的 connect() 阻塞到断开连接，由调用方放后台任务
        await self._danmaku.connect()
        logger.info("已连接 B 站直播间 %s 弹幕服务器", self.room_id)

    async def disconnect(self):
        try:
            await self._danmaku.disconnect()
        except Exception:
            pass
        logger.info("已断开直播间 %s", self.room_id)
