"""欢迎进场 / 感谢礼物 / 感谢关注的话术模板。"""
import random

from ..config import CONFIG


def _pick(templates: list[str]) -> str:
    return random.choice(templates)


def fill(template: str, **params) -> str:
    out = template
    for key, value in params.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def entrance(username: str) -> str | None:
    cfg = CONFIG["greet"]
    if not cfg.get("entrance_enable"):
        return None
    return fill(_pick(cfg["entrance_templates"]), username=username)


def gift(username: str, gift_name: str, num: int) -> str | None:
    cfg = CONFIG["greet"]
    if not cfg.get("gift_enable"):
        return None
    return fill(_pick(cfg["gift_templates"]), username=username, gift_name=gift_name, gift_num=num)


def follow(username: str) -> str | None:
    cfg = CONFIG["greet"]
    if not cfg.get("follow_enable"):
        return None
    return fill(_pick(cfg["follow_templates"]), username=username)


def like(username: str) -> str | None:
    cfg = CONFIG["greet"]
    if not cfg.get("like_enable"):
        return None
    templates = cfg.get("like_templates") or ["谢谢 {username} 点赞"]
    return fill(_pick(templates), username=username)
