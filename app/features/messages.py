"""消息持久化：直播事件与 AI 回复写入 SQLite，页面刷新后可回看。

保留最近 MAX_ROWS 条，写入时顺带清理。
"""
import sqlite3
import time
from pathlib import Path

from ..config import CONFIG, ROOT

MAX_ROWS = 5000
_PRUNE_EVERY = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    username TEXT,
    content TEXT,
    ai_reply TEXT
)
"""

# ws 事件类型 → 消息分类（与前端筛选一致）
_TYPE_MAP = {
    "danmu": "chat", "reply": "chat", "keyword": "chat",
    "welcome": "enter", "gift_thanks": "gift", "like": "like",
    "follow_thanks": "follow", "fanclub": "fanclub",
    "manual": "cast", "schedule": "cast", "trends": "cast", "points": "cast",
    "song": "cast", "song_miss": "cast", "song_stop": "cast", "like_thanks": "cast",
}
SKIP_TYPES = {"status", "ai_reply", "song_play"}


class MessageLog:
    def __init__(self, db_path: str):
        path = ROOT / db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._count = 0

    def add(self, type_: str, username: str = "", content: str = "", ai_reply: str = ""):
        if type_ in SKIP_TYPES:
            return
        cat = _TYPE_MAP.get(type_, "cast")
        ts = time.strftime("%H:%M:%S")
        with self._conn:
            self._conn.execute(
                "INSERT INTO messages(ts, type, username, content, ai_reply) VALUES(?,?,?,?,?)",
                (ts, cat, username, content, ai_reply),
            )
        self._count += 1
        if self._count >= _PRUNE_EVERY:
            self._count = 0
            with self._conn:
                self._conn.execute(
                    "DELETE FROM messages WHERE seq NOT IN "
                    "(SELECT seq FROM messages ORDER BY seq DESC LIMIT ?)", (MAX_ROWS,))

    def recent(self, limit: int = 300, since_id: int = 0) -> list[dict]:
        cur = self._conn.execute(
            "SELECT seq, ts, type, username, content, ai_reply FROM messages "
            "WHERE seq > ? ORDER BY seq DESC LIMIT ?",
            (since_id, limit),
        )
        return [
            {"seq": r[0], "ts": r[1], "type": r[2], "username": r[3],
             "content": r[4], "ai_reply": r[5]}
            for r in cur.fetchall()
        ]
