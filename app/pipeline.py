"""AI 主播核心管线：事件接入 → 路由 → 单队列顺序处理 → TTS → WebSocket 推送。

路由规则（弹幕）：违禁词过滤 → 点歌指令 → 积分指令 → 按用户限流 → LLM 回复。
所有待播报内容进同一个单消费者队列，保证播出顺序；排队超时的任务被丢弃。
"""
import asyncio
import logging
import time
from dataclasses import dataclass

from .config import CONFIG
from .danmu.bilibili import BilibiliDanmuClient
from .danmu.douyin import DouyinSourceClient
from .filter.badwords import check, check_ai
from .features import greet, integral, keywords, songs
from .features.schedule import Scheduler
from .llm import openai_compat as llm
from .memory import Memory
from .stats import Stats
from .tts import synthesize
from .ws import WsManager

logger = logging.getLogger("anchor")

SAFE_FALLBACK = "收到！"
SAFE_REPLY = "这个话题我们聊点别的吧"


@dataclass
class Task:
    kind: str                     # reply / keyword / song / welcome / gift_thanks / follow_thanks / like_thanks / schedule / trends / points / song_miss / song_stop
    username: str
    text: str                     # reply: 用户弹幕；其余: 要朗读的文本
    audio_url: str | None = None  # song_play 事件附带的歌声音频
    deadline: float = 0.0         # 单调时钟，超过即丢弃
    question: str = ""            # keyword 回复时对应的原弹幕，用于前端行匹配


class AnchorPipeline:
    def __init__(self):
        self.ws = WsManager()
        self.memory = Memory(
            max_turns=CONFIG["reply"].get("max_turns", 6),
            per_user_interval=CONFIG["reply"].get("per_user_interval", 8.0),
        )
        self.integral = integral.Integral(CONFIG["integral"]["db_path"])
        self.scheduler = Scheduler(self.enqueue_broadcast, self.get_viewer_count, llm.rewrite)
        self.stats = Stats()
        self.ai_reply_enabled = True

        self.danmu_client = None
        self.current_platform = CONFIG["platform"]
        self.connect_task: asyncio.Task | None = None
        self.source_task: asyncio.Task | None = None
        self.queue: asyncio.Queue[Task] = asyncio.Queue()
        self.worker: asyncio.Task | None = None
        self._viewer_ts = 0.0
        self._like_buffer = 0

    # ---------- 启停 ----------

    async def start(self, room_id=None, platform: str | None = None):
        if self.danmu_client is not None:
            raise RuntimeError("弹幕监听已在运行，请先停止")
        self.current_platform = platform or CONFIG["platform"]
        await self._ensure_worker()
        await self.scheduler.start()
        if self.current_platform == "bilibili":
            rid = int(room_id or CONFIG["bilibili"]["room_id"])
            client = BilibiliDanmuClient(
                rid,
                sessdata=CONFIG["bilibili"].get("sessdata", ""),
                danmu_handler=self._on_danmu,
                enter_handler=self._on_enter,
                gift_handler=self._on_gift,
                follow_handler=self._on_follow,
                like_handler=self._on_like,
                fanclub_handler=self._on_fanclub,
            )
            # v17 的 connect() 会阻塞到断开连接，必须放后台任务；
            # 轮询连接状态，认证成功立即返回（否则接口要干等超时）
            self.connect_task = asyncio.create_task(client.connect())
            self.danmu_client = client
            for _ in range(50):  # 最多 10 秒
                if self.connect_task.done():
                    exc = self.connect_task.exception()
                    self.danmu_client = None
                    self.connect_task = None
                    raise RuntimeError(f"B 站弹幕连接失败: {exc or '连接异常退出'}")
                if client.danmaku_status() == client.STATUS_ESTABLISHED:
                    break
                await asyncio.sleep(0.2)
            else:
                await self.stop()
                raise RuntimeError("B 站弹幕连接超时（10 秒），请检查房间号或网络")
            await self.ws.broadcast("status", running=True, room_id=rid, platform=self.current_platform)
        elif self.current_platform == "douyin":
            client = DouyinSourceClient(
                CONFIG["douyin"]["source_url"],
                str(room_id or CONFIG["douyin"]["room_id"]),
                self._on_source_event,
            )
            await client.start()
            self.danmu_client = client
            await self.ws.broadcast("status", running=True,
                                    room_id=CONFIG["douyin"]["room_id"], platform=self.current_platform)
        else:
            raise ValueError(f"未知 platform: {self.current_platform}")
        logger.info("已启动平台 %s", self.current_platform)

    async def stop(self):
        if self.danmu_client:
            client, self.danmu_client = self.danmu_client, None
            if isinstance(client, DouyinSourceClient):
                await client.stop()
            else:
                await client.disconnect()
        if self.connect_task:
            self.connect_task.cancel()
            self.connect_task = None
        await self.scheduler.stop()
        await self.ws.broadcast("status", running=False, platform=self.current_platform)

    # ---------- 事件入口 ----------

    async def _on_source_event(self, etype: str, payload: dict):
        """抖音弹幕源统一事件入口。"""
        username = str(payload.get("username") or "")
        if etype == "danmu":
            await self._on_danmu(username, str(payload.get("text") or ""))
        elif etype == "enter":
            await self._on_enter(username)
        elif etype == "gift":
            await self._on_gift(username, str(payload.get("gift_name") or "礼物"),
                                int(payload.get("gift_num") or 1), 0.0)
        elif etype == "follow":
            await self._on_follow(username)
        elif etype == "like":
            await self._on_like(username, int(payload.get("count") or 1))
        elif etype == "fanclub":
            await self._on_fanclub(username)

    async def _on_danmu(self, username: str, text: str):
        self.stats.add_danmu(text)
        await self.ws.broadcast("danmu", username=username, text=text)
        ok, reason = check(text)
        if not ok:
            await self.ws.broadcast("blocked", username=username, text=text, reason=reason)
            return

        # 指令系统最优先
        song_match = songs.match(text)
        if song_match:
            await self._handle_song(username, song_match)
            return

        # 积分指令
        if self.integral.is_sign_cmd(text):
            result, pts, days = self.integral.sign(username)
            if result == "ok":
                await self.enqueue_broadcast(
                    f"{username} 签到成功，获得 {pts} 积分，已累计签到 {days} 天", "points", username)
            elif result == "already":
                total, _ = self.integral.get(username)
                await self.enqueue_broadcast(
                    f"{username} 今天已经签到过啦，当前积分 {total}", "points", username)
            return
        if self.integral.is_query_cmd(text):
            total, days = self.integral.get(username)
            await self.enqueue_broadcast(
                f"{username} 当前积分 {total}，累计签到 {days} 天", "points", username)
            return

        # 关键词回复优先于 AI：命中直接预置话术回复，不受限流影响
        keyword_reply = keywords.match(text, username)
        if keyword_reply is not None:
            await self._ensure_worker()
            await self._put_task(Task("keyword", username, keyword_reply,
                                      question=text,
                                      deadline=time.monotonic()
                                      + CONFIG["reply"].get("queue_timeout", 25)))
            return

        # AI 触发过滤规则：只影响是否进 LLM，弹幕照常显示
        ai_ok, filter_reason = check_ai(text, username)
        if not ai_ok:
            await self.ws.broadcast("filtered", username=username, text=text,
                                    reason=filter_reason)
            return

        # 启用AI回复开关关闭时，弹幕只展示不回复（点歌/积分/关键词指令仍有效）
        if not self.ai_reply_enabled:
            return

        # 按用户限流
        allowed, wait = self.memory.allow_reply(username)
        if not allowed:
            await self.ws.broadcast("ratelimited", username=username, text=text,
                                    wait=round(wait, 1))
            return

        timeout = CONFIG["reply"].get("queue_timeout", 25)
        self.memory.mark_reply(username)
        await self._ensure_worker()
        await self._put_task(Task("reply", username, text, deadline=time.monotonic() + timeout))

    async def _on_enter(self, username: str):
        self.stats.add("enter")
        self.integral.add_entrance(username)
        text = greet.entrance(username)
        if text:
            await self.enqueue_broadcast(text, "welcome", username, fresh=True)

    async def _on_gift(self, username: str, gift_name: str, num: int, price_yuan: float):
        self.stats.add("gift", num)
        self.integral.add_gift(username, price_yuan)
        text = greet.gift(username, gift_name, num)
        if text:
            await self.enqueue_broadcast(text, "gift_thanks", username, fresh=True)

    async def _on_follow(self, username: str):
        self.stats.add("follow")
        text = greet.follow(username)
        if text:
            await self.enqueue_broadcast(text, "follow_thanks", username, fresh=True)

    async def _handle_song(self, username: str, match: tuple[str, str]):
        action, name = match
        if action == songs.STOP:
            await self.enqueue_broadcast("好的，取消点歌", "song_stop", username, fresh=True)
            return
        song = songs.random_song() if action == songs.RANDOM else (songs.find(name) if name else None)
        if song is None:
            cfg = CONFIG["song"]
            text = (cfg.get("miss_templates") or ["抱歉，我还没学会唱 {song}"])[0]
            text = greet.fill(text, song=name or "这首歌")
            await self.enqueue_broadcast(text, "song_miss", username, fresh=True)
            return
        announce = f"接下来为大家播放《{song.stem}》"
        await self._put_task(Task("song", username, announce, audio_url=f"/audio/{song.name}"))

    # ---------- 队列消费 ----------

    async def _ensure_worker(self):
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._reply_worker())

    async def _reply_worker(self):
        while True:
            task = await self.queue.get()
            try:
                if task.deadline and time.monotonic() > task.deadline:
                    await self.ws.broadcast("skipped", username=task.username,
                                            text=task.text, kind=task.kind)
                    continue
                if task.kind == "reply":
                    await self._reply(task)
                elif task.kind == "keyword":
                    await self._keyword(task)
                elif task.kind == "song":
                    audio = await synthesize(task.text)
                    await self.ws.broadcast("song", username=task.username, text=task.text,
                                            audio_url=f"/audio/{audio.name}" if audio else None)
                    await self.ws.broadcast("song_play", username=task.username,
                                            text=task.audio_url, audio_url=task.audio_url)
                else:
                    await self._speak(task)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("处理任务失败: %r", task)
            finally:
                self.queue.task_done()

    async def _speak(self, task: Task):
        """通用播报：文本合成语音后广播，事件类型与任务类型同名。"""
        audio = await synthesize(task.text)
        await self.ws.broadcast(task.kind, username=task.username, text=task.text,
                                audio_url=f"/audio/{audio.name}" if audio else None)

    async def _keyword(self, task: Task):
        """关键词回复：预置话术直接播出，事件仍走 reply 通道便于前端回填。"""
        audio = await synthesize(task.text)
        await self.ws.broadcast("reply", username=task.username, question=task.question,
                                text=task.text, source="keyword",
                                audio_url=f"/audio/{audio.name}" if audio else None)

    async def _reply(self, task: Task):
        username, text = task.username, task.text

        history = self.memory.context(username)
        reply = await llm.chat(text, history)
        if reply is None:
            reply = f"收到！你说的是：{text}（未配置 LLM，这是兜底回复）"

        ok, reason = check(reply)
        if not ok:
            logger.warning("LLM 回复被过滤（%s）：%s", reason, reply)
            reply = SAFE_REPLY

        self.memory.add(username, "user", text)
        self.memory.add(username, "assistant", reply)

        audio = await synthesize(reply)
        await self.ws.broadcast("reply", username=username, question=text, text=reply,
                                source="ai",
                                audio_url=f"/audio/{audio.name}" if audio else None)

    # ---------- 路由诊断 ----------

    def route_decision(self, text: str, username: str = "测试用户") -> dict:
        """只做路由判断，不产生任何播出副作用。供测试回复接口使用。"""
        ok, reason = check(text)
        if not ok:
            return {"action": "blocked", "reason": reason}
        if songs.match(text):
            return {"action": "song"}
        if self.integral.is_sign_cmd(text) or self.integral.is_query_cmd(text):
            return {"action": "integral"}
        kw = keywords.match(text, username)
        if kw is not None:
            return {"action": "keyword", "reply": kw}
        ai_ok, freason = check_ai(text, username)
        if not ai_ok:
            return {"action": "filtered", "reason": freason}
        if not self.ai_reply_enabled:
            return {"action": "ai_disabled"}
        allowed, wait = self.memory.allow_reply(username)
        if not allowed:
            return {"action": "ratelimited", "wait": round(wait, 1)}
        return {"action": "llm"}

    # ---------- 供外部调用 ----------

    async def _put_task(self, task: Task):
        """入队带洪峰保护：队列满时丢弃新任务并广播提示，防止事件风暴拖垮播出。"""
        max_q = CONFIG["reply"].get("queue_max", 50)
        if self.queue.qsize() >= max_q:
            await self.ws.broadcast("skipped", username=task.username, text=task.text,
                                    kind=f"{task.kind}(队列已满)")
            return
        await self.queue.put(task)

    async def enqueue_broadcast(self, text: str, kind: str, username: str = "直播间",
                                fresh: bool = False):
        """加入待播报队列（欢迎/感谢/定时播报等）。fresh=True 时设置超时丢弃。"""
        timeout = CONFIG["reply"].get("queue_timeout", 25) if fresh else 0
        await self._ensure_worker()
        deadline = time.monotonic() + timeout if timeout > 0 else 0.0
        await self._put_task(Task(kind, username, text, deadline=deadline))

    async def refresh_viewers(self):
        """拉取在线/累计观看人数到统计缓存（10 秒 TTL，避免轮询打爆接口）。"""
        if time.monotonic() - self._viewer_ts < 10:
            return
        try:
            from bilibili_api import live
            rid = int(CONFIG["bilibili"]["room_id"])
            info = await live.LiveRoom(room_display_id=rid).get_online_info()
            self.stats.online = int(info.get("online") or 0)
            self.stats.cumulative = int(info.get("count") or info.get("cumulative") or 0)
            self._viewer_ts = time.monotonic()
        except Exception:
            pass

    async def _on_like(self, username: str, count: int):
        self.stats.add("like", count)
        await self.ws.broadcast("like", username=username, count=count)
        # 点赞累计达到阈值时感谢一次
        gcfg = CONFIG["greet"]
        if gcfg.get("like_enable"):
            self._like_buffer += count
            if self._like_buffer >= int(gcfg.get("like_min_count", 5)):
                self._like_buffer = 0
                text = greet.like(username)
                if text:
                    await self.enqueue_broadcast(text, "like_thanks", username, fresh=True)

    async def _on_fanclub(self, username: str):
        self.stats.add("fanclub")
        await self.ws.broadcast("fanclub", username=username)

    async def manual_speak(self, text: str):
        """实时话术：手动让主播说一句话。"""
        await self.enqueue_broadcast(text, "manual", fresh=True)

    def status(self) -> dict:
        return {
            "running": self.danmu_client is not None,
            "platform": self.current_platform,
            "ai_reply_enabled": self.ai_reply_enabled,
            "queue_size": self.queue.qsize(),
            **self.stats.snapshot(),
        }

    async def get_viewer_count(self) -> int:
        try:
            from bilibili_api import live
            rid = int(CONFIG["bilibili"]["room_id"])
            room = live.LiveRoom(room_display_id=rid)
            info = await room.get_online_info()
            return int(info.get("online") or info.get("count") or 0)
        except Exception:
            return 0
