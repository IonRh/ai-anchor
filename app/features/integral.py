"""积分系统：进场/礼物/签到得分，SQLite 持久化。"""
import sqlite3
from datetime import date
from pathlib import Path

from ..config import CONFIG, ROOT

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    name TEXT PRIMARY KEY,
    points INTEGER NOT NULL DEFAULT 0,
    sign_days INTEGER NOT NULL DEFAULT 0,
    last_sign TEXT
)
"""


class Integral:
    def __init__(self, db_path: str):
        path = ROOT / db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @property
    def cfg(self) -> dict:
        return CONFIG["integral"]

    def _add(self, username: str, points: int):
        with self._conn:
            self._conn.execute(
                "INSERT INTO users(name, points) VALUES(?, ?) "
                "ON CONFLICT(name) DO UPDATE SET points = points + excluded.points",
                (username, points),
            )

    def get(self, username: str) -> tuple[int, int]:
        """返回 (积分, 累计签到天数)。"""
        row = self._conn.execute(
            "SELECT points, sign_days FROM users WHERE name = ?", (username,)
        ).fetchone()
        return (row[0], row[1]) if row else (0, 0)

    def add_entrance(self, username: str):
        if self.cfg.get("enable") and self.cfg.get("entrance_points"):
            self._add(username, self.cfg["entrance_points"])

    def add_gift(self, username: str, price_yuan: float):
        pts = self.cfg.get("gift_points_per_yuan")
        if self.cfg.get("enable") and pts and price_yuan > 0:
            self._add(username, max(1, int(price_yuan * pts)))

    def sign(self, username: str) -> tuple[str, int, int]:
        """签到。返回 (结果, 本次积分, 累计签到天数)，结果为 ok/already/disabled。"""
        if not self.cfg.get("enable") or not self.cfg.get("sign_points"):
            return "disabled", 0, 0
        today = date.today().isoformat()
        row = self._conn.execute(
            "SELECT last_sign, sign_days FROM users WHERE name = ?", (username,)
        ).fetchone()
        if row and row[0] == today:
            return "already", 0, row[1]
        pts = self.cfg["sign_points"]
        self._add(username, pts)
        with self._conn:
            self._conn.execute(
                "INSERT INTO users(name, points, sign_days, last_sign) VALUES(?, ?, 1, ?) "
                "ON CONFLICT(name) DO UPDATE SET sign_days = sign_days + 1, last_sign = ?",
                (username, pts, today, today),
            )
        _, days = self.get(username)
        return "ok", pts, days

    def is_sign_cmd(self, text: str) -> bool:
        return text.strip() in self.cfg.get("sign_cmds", [])

    def is_query_cmd(self, text: str) -> bool:
        return text.strip() in self.cfg.get("query_cmds", [])
