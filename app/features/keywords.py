"""关键词回复：命中关键词直接用预置话术回复，优先于 LLM。

config.json:
  "keywords": {
    "enable": true,
    "rules": [
      {"keys": ["谢谢", "感谢"], "replies": ["不客气呀 {username}", "小意思啦"]}
    ]
  }
keys / replies 都支持多条（随机选一条回复）；keys 支持 re: 正则前缀与 * 通配。
"""
import fnmatch
import logging
import random
import re

from ..config import CONFIG
from .greet import fill

logger = logging.getLogger(__name__)


def _hit(key: str, text: str) -> bool:
    key = key.strip()
    if not key:
        return False
    if key.startswith("re:"):
        try:
            return re.search(key[3:], text) is not None
        except re.error:
            logger.warning("无效关键词正则: %s", key)
            return False
    if "*" in key or "?" in key:
        return fnmatch.fnmatch(text, f"*{key}*") or fnmatch.fnmatch(text, key)
    return key in text


def match(text: str, username: str = "") -> str | None:
    """返回命中的回复文本；未命中或未启用返回 None。"""
    cfg = CONFIG.get("keywords") or {}
    if not cfg.get("enable"):
        return None
    for rule in cfg.get("rules") or []:
        keys = rule.get("keys") or []
        replies = [r for r in (rule.get("replies") or []) if r.strip()]
        if not keys or not replies:
            continue
        if any(_hit(k, text) for k in keys):
            return fill(random.choice(replies), username=username)
    return None
