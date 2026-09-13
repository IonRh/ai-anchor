"""OBS 推流对接。

数字人/字幕页用 static/overlay.html（OBS 浏览器源加载），音频在页面内播放，
OBS 捕获该页面 + 系统声音后推 RTMP 到平台。本模块负责检测/拉起 OBS 进程。
"""
import logging
import subprocess

from ..config import CONFIG

logger = logging.getLogger(__name__)


def _obs_running(image_name: str) -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        return image_name.lower() in (out.stdout or "").lower()
    except Exception:
        return False


async def start_obs() -> dict:
    """按 config streaming.obs 配置拉起 OBS。已运行则直接返回提示。"""
    cfg = CONFIG["streaming"]["obs"]
    if not cfg.get("enable"):
        return {"ok": False, "error": "config.json streaming.obs.enable 未开启"}

    image_name = cfg["path"].replace("/", "\\").rsplit("\\", 1)[-1]
    if _obs_running(image_name):
        return {"ok": True, "message": f"{image_name} 已在运行"}

    try:
        subprocess.Popen([cfg["path"], *cfg.get("args", [])])
        return {
            "ok": True,
            "message": f"已启动 {image_name}。请在 OBS 中添加浏览器源："
                       f"http://127.0.0.1:{CONFIG['server']['port']}/overlay.html ，"
                       "并勾选'控制 OBS 通过浏览器源的音频'或直接捕获系统声音（虚拟声卡）后开始推流。",
        }
    except Exception as e:
        return {"ok": False, "error": f"启动 OBS 失败：{e}（请检查 streaming.obs.path）"}
