"""每用户多轮上下文记忆 + 按用户回复限流。

历史与时间戳都有容量上限，防止长时间直播内存无限增长。
"""
import time
from collections import OrderedDict, defaultdict, deque

MAX_USERS = 300


class Memory:
    def __init__(self, max_turns: int = 6, per_user_interval: float = 8.0):
        self.max_turns = max_turns
        self.per_user_interval = per_user_interval
        self._history: OrderedDict[str, deque] = OrderedDict()
        self._last_reply: OrderedDict[str, float] = OrderedDict()

    def _touch_history(self, username: str) -> deque:
        dq = self._history.get(username)
        if dq is None:
            dq = deque(maxlen=self.max_turns * 2)
            self._history[username] = dq
            while len(self._history) > MAX_USERS:
                self._history.popitem(last=False)
        else:
            self._history.move_to_end(username)
        return dq

    def context(self, username: str) -> list[dict]:
        """返回该用户的对话历史（OpenAI messages 格式，不含 system）。"""
        dq = self._history.get(username)
        if not dq:
            return []
        self._history.move_to_end(username)
        return [
            {"role": "user" if role == "user" else "assistant", "content": content}
            for role, content in dq
        ]

    def add(self, username: str, role: str, content: str):
        self._touch_history(username).append((role, content))

    def allow_reply(self, username: str) -> tuple[bool, float]:
        """按用户限流：距离上次回复不足间隔时拒绝。返回 (是否放行, 还需等待秒数)。"""
        last = self._last_reply.get(username)
        if last is None:
            return True, 0.0
        self._last_reply.move_to_end(username)
        wait = self.per_user_interval - (time.monotonic() - last)
        if wait > 0:
            return False, wait
        return True, 0.0

    def mark_reply(self, username: str):
        self._last_reply[username] = time.monotonic()
        self._last_reply.move_to_end(username)
        while len(self._last_reply) > MAX_USERS:
            self._last_reply.popitem(last=False)
