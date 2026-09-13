"""点歌：弹幕触发词匹配本地歌曲目录（mp3/wav 文件名模糊匹配）。"""
import random
from pathlib import Path

from ..config import CONFIG, ROOT

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a"}

START, STOP, RANDOM = "start", "stop", "random"


def match(text: str) -> tuple[str, str] | None:
    """返回 (动作, 歌名或空)，不匹配返回 None。"""
    cfg = CONFIG["song"]
    if not cfg.get("enable"):
        return None
    text = text.strip()
    start_cmd = cfg["start_cmd"]
    if start_cmd and text.startswith(start_cmd):
        return START, text[len(start_cmd):].strip()
    if cfg["stop_cmd"] and text == cfg["stop_cmd"]:
        return STOP, ""
    if cfg["random_cmd"] and text == cfg["random_cmd"]:
        return RANDOM, ""
    return None


def _song_dir() -> Path:
    path = ROOT / CONFIG["song"]["folder"]
    path.mkdir(parents=True, exist_ok=True)
    return path


def _all_songs() -> list[Path]:
    return sorted(p for p in _song_dir().iterdir() if p.suffix.lower() in AUDIO_EXTS)


def find(name: str) -> Path | None:
    for p in _all_songs():
        if name in p.stem:
            return p
    return None


def random_song() -> Path | None:
    songs = _all_songs()
    return random.choice(songs) if songs else None
