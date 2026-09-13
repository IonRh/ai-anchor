"""直播间统计：各类事件计数、表情统计、观看人数缓存。"""
import re
from collections import Counter

# unicode emoji（含扩展区）与 B 站表情 [xxx]
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2190-\u21FF\u2B00-\u2BFF]|\\[[^\\[\\]]{1,12}\\]"
)


class Stats:
    def __init__(self):
        self.counters = {"danmu": 0, "enter": 0, "gift": 0, "follow": 0,
                         "like": 0, "fanclub": 0}
        self.emojis: Counter[str] = Counter()
        self.online = 0
        self.cumulative = 0

    def add(self, kind: str, n: int = 1):
        if kind in self.counters:
            self.counters[kind] += n

    def add_danmu(self, text: str):
        self.add("danmu")
        for m in _EMOJI_RE.findall(text):
            self.emojis[m] += 1

    def top_emojis(self, n: int = 8) -> list[tuple[str, int]]:
        return self.emojis.most_common(n)

    def snapshot(self) -> dict:
        return {
            "counters": dict(self.counters),
            "top_emojis": self.top_emojis(),
            "online": self.online,
            "cumulative": self.cumulative,
        }
