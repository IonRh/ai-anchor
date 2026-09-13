"""WebSocket 连接管理与事件广播。广播的同时可选持久化到消息库。"""
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WsManager:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.recorder = None   # MessageLog 实例，由 main 注入

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def broadcast(self, type_: str, **data):
        if self.recorder is not None:
            try:
                self.recorder.add(
                    type_,
                    username=str(data.get("username") or ""),
                    content=str(data.get("question") or data.get("text") or ""),
                    ai_reply=str(data.get("text") or "") if type_ == "reply" else "",
                )
            except Exception:
                logger.exception("消息持久化失败")
        if not self.clients:
            return
        message = json.dumps({"type": type_, **data}, ensure_ascii=False)
        dead = []
        for ws in self.clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)
