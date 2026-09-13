"""弹幕过滤：违禁词 + 长度 + AI 触发过滤规则（内容/用户名，支持通配符和 re: 正则）。

两组规则的区别：
- check():    违禁词/长度，命中后弹幕按"拦截"处理（不显示回复）。
- check_ai(): 内容/用户名过滤规则，只影响是否触发 AI 回复，弹幕本身照常显示。
"""
import fnmatch
import logging
import re
from pathlib import Path

from ..config import CONFIG, ROOT

logger = logging.getLogger(__name__)


def _load_badwords() -> set[str]:
    path = ROOT / CONFIG["filter"]["badwords_path"]
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


BADWORDS = _load_badwords()


def _rule_hit(rule: str, text: str) -> bool:
    """单条过滤规则：re: 前缀按正则，含 * 按 fnmatch 通配，否则子串匹配。忽略 # 注释行。"""
    rule = rule.strip()
    if not rule or rule.startswith("#"):
        return False
    if rule.startswith("re:"):
        try:
            return re.search(rule[3:], text) is not None
        except re.error:
            logger.warning("无效正则规则: %s", rule)
            return False
    if "*" in rule or "?" in rule:
        return fnmatch.fnmatch(text, f"*{rule}*") or fnmatch.fnmatch(text, rule)
    return rule in text


def check(text: str) -> tuple[bool, str]:
    """违禁词/长度检查。返回 (是否放行, 说明)。"""
    max_len = CONFIG["filter"]["max_len"]
    if len(text) > max_len:
        return False, f"超过最大长度 {max_len}"
    for word in BADWORDS:
        if word in text:
            return False, f"命中违禁词: {word}"
    return True, ""


def check_ai(text: str, username: str = "") -> tuple[bool, str]:
    """AI 触发过滤规则检查（不影响关键词回复与弹幕显示）。返回 (是否触发AI, 说明)。"""
    cfg = CONFIG["filter"]
    for rule in cfg.get("content_rules") or []:
        if _rule_hit(rule, text):
            return False, f"命中内容规则: {rule}"
    for rule in cfg.get("username_rules") or []:
        if _rule_hit(rule, username):
            return False, f"命中用户名规则: {rule}"
    return True, ""
