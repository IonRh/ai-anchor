"""AI 主播后端主服务。

链路：B 站弹幕 → 过滤 → LLM → edge-tts → WebSocket 推给前端播放。
用单消费者队列保证回复按弹幕顺序产出，不并发抢跑。
"""
import asyncio
import io
import json
import logging
import re
import zipfile
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .config import CONFIG, ROOT
from .features.messages import MessageLog
from .pipeline import AnchorPipeline
from .streaming import obs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("anchor")

app = FastAPI(title="AI Anchor Backend")

pipeline = AnchorPipeline()
pipeline.ws.recorder = MessageLog(CONFIG.get("messages_db", "data/messages.db"))


class StartRequest(BaseModel):
    room_id: int | str | None = None
    platform: str | None = None   # bilibili | douyin，不传用 config 当前值


class TestEventRequest(BaseModel):
    type: str = "danmu"        # danmu | enter | gift | follow | like | fanclub
    username: str = "测试观众"
    text: str = ""
    gift_name: str = "小花花"
    gift_num: int = 1


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/overlay.html")
async def overlay():
    return FileResponse(ROOT / "static" / "overlay.html")


@app.get("/mobile.html")
async def mobile_page():
    return FileResponse(ROOT / "static" / "mobile.html")


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(ROOT / "static" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(ROOT / "static" / "sw.js", media_type="text/javascript")


@app.get("/icons/{name}")
async def icons(name: str):
    path = (ROOT / "static" / "icons" / Path(name).name).resolve()
    if not path.is_file():
        return Response(status_code=404)
    return Response(content=path.read_bytes(), media_type="image/png")


@app.post("/api/start")
async def api_start(req: StartRequest):
    try:
        await pipeline.start(req.room_id, req.platform)
        return {"ok": True}
    except Exception as e:
        logger.exception("启动失败")
        return {"ok": False, "error": str(e)}


@app.post("/api/stop")
async def api_stop():
    await pipeline.stop()
    return {"ok": True}


@app.post("/api/obs/start")
async def api_obs_start():
    """拉起 OBS（需在 config.json streaming.obs 里启用并配置路径）。"""
    return await obs.start_obs()


@app.post("/api/test_event")
async def api_test_event(req: TestEventRequest):
    """开发调试：模拟一条直播事件走完整链路，不依赖真实直播间。"""
    if req.type == "danmu":
        await pipeline._on_danmu(req.username, req.text)
    elif req.type == "enter":
        await pipeline._on_enter(req.username)
    elif req.type == "gift":
        await pipeline._on_gift(req.username, req.gift_name, req.gift_num, 0.5)
    elif req.type == "follow":
        await pipeline._on_follow(req.username)
    elif req.type == "like":
        await pipeline._on_like(req.username, 1)
    elif req.type == "fanclub":
        await pipeline._on_fanclub(req.username)
    else:
        return {"ok": False, "error": f"未知事件类型 {req.type}"}
    return {"ok": True}


@app.get("/api/tts")
async def api_tts(text: str):
    """手动测试 TTS：浏览器直接访问 /api/tts?text=你好 即可听到声音。"""
    from .tts import synthesize
    audio_path = await synthesize(text)
    if audio_path is None:
        return Response(status_code=503)
    return Response(content=audio_path.read_bytes(), media_type=_media_type(audio_path))


@app.get("/audio/{name}")
async def audio(name: str):
    from .config import CONFIG as C
    from .features.songs import _song_dir
    # 允许访问 TTS 输出目录与点歌目录
    allowed_dirs = [(ROOT / C["tts"]["out_dir"]).resolve(), _song_dir().resolve()]
    for out_dir in allowed_dirs:
        path = (out_dir / name).resolve()
        if path.is_relative_to(out_dir) and path.exists():
            return Response(content=path.read_bytes(), media_type=_media_type(path))
    return Response(status_code=404)


def _media_type(path) -> str:
    return {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
    }.get(path.suffix.lower(), "application/octet-stream")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await pipeline.ws.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pipeline.ws.disconnect(ws)


# ---------------- 中控台管理接口 ----------------


class ToggleRequest(BaseModel):
    enabled: bool


class SpeakRequest(BaseModel):
    text: str


class TestReplyRequest(BaseModel):
    text: str
    username: str = "测试用户"


@app.post("/api/test_reply")
async def api_test_reply(req: TestReplyRequest):
    """测试回复：诊断一条弹幕会走哪条路由（关键词/LLM/过滤/限流…），不产生播出。"""
    return pipeline.route_decision(req.text, req.username)


@app.get("/api/messages")
async def api_messages(limit: int = 300, since_id: int = 0):
    """历史消息（刷新不丢），新消息在前。"""
    rows = pipeline.ws.recorder.recent(limit=min(limit, 2000), since_id=since_id)
    return {"ok": True, "messages": rows}


@app.get("/api/llm/models")
async def llm_models():
    """从 LLM 服务拉取可用模型列表（OpenAI 兼容 /models 接口）。"""
    cfg = CONFIG["llm"]
    if not cfg.get("api_key"):
        return {"ok": False, "error": "请先填写 API Key"}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{cfg['base_url'].rstrip('/')}/models",
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            models = sorted({m.get("id") for m in data if m.get("id")})
            return {"ok": True, "models": models}
    except Exception as e:
        return {"ok": False, "error": f"拉取失败：{e}"}


@app.get("/api/console/status")
async def console_status():
    """运行状态概览：连接、各类事件计数、观看人数、表情统计。"""
    if pipeline.danmu_client is not None and CONFIG["platform"] == "bilibili":
        await pipeline.refresh_viewers()
    return pipeline.status()


@app.post("/api/ai_reply")
async def ai_reply_toggle(req: ToggleRequest):
    pipeline.ai_reply_enabled = req.enabled
    await pipeline.ws.broadcast("ai_reply", enabled=req.enabled)
    return {"ok": True, "enabled": req.enabled}


@app.post("/api/speak")
async def api_speak(req: SpeakRequest):
    """实时话术：让主播立即朗读一段文字。"""
    text = req.text.strip()
    if not text:
        return {"ok": False, "error": "内容为空"}
    await pipeline.manual_speak(text)
    return {"ok": True}


@app.get("/api/settings")
async def get_settings():
    return CONFIG


@app.post("/api/settings")
async def save_settings(request: Request):
    """合并保存设置：body 为 config.json 的一个或多个顶层段。"""
    try:
        incoming = await request.json()
    except Exception:
        return {"ok": False, "error": "请求体不是合法 JSON"}
    if not isinstance(incoming, dict):
        return {"ok": False, "error": "请求体应为 JSON 对象"}

    for section, value in incoming.items():
        if section in ("platform", "server", "streaming"):
            return {"ok": False, "error": f"段 {section} 请直接编辑 config.json 修改"}
        if section in CONFIG and isinstance(value, dict) and isinstance(CONFIG[section], dict):
            CONFIG[section].update(value)
        else:
            CONFIG[section] = value

    with open(ROOT / "config.json", "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, ensure_ascii=False, indent=2)

    # 热更新可运行时生效的参数
    pipeline.memory.per_user_interval = CONFIG["reply"].get("per_user_interval", 8.0)
    return {"ok": True}


# 音频/话术文件管理：目录白名单
_MANAGE_DIRS = {"songs": CONFIG["song"]["folder"], "trends": CONFIG["trends"]["folder"]}


def _manage_dir(dir_key: str) -> Path | None:
    rel = _MANAGE_DIRS.get(dir_key)
    if not rel:
        return None
    path = (ROOT / rel).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


@app.get("/api/files")
async def list_files(dir: str):
    base = _manage_dir(dir)
    if base is None:
        return {"ok": False, "error": "目录不支持"}
    files = []
    for p in sorted(base.iterdir()):
        if p.is_file():
            files.append({"name": p.name, "size": p.stat().st_size})
    return {"ok": True, "dir": dir, "files": files}


@app.get("/api/files/content")
async def file_content(dir: str, name: str):
    base = _manage_dir(dir)
    if base is None:
        return {"ok": False, "error": "目录不支持"}
    path = (base / name).resolve()
    if not path.is_relative_to(base) or not path.exists():
        return {"ok": False, "error": "文件不存在"}
    return {"ok": True, "name": name, "content": path.read_text(encoding="utf-8", errors="replace")}


@app.post("/api/files/content")
async def save_file(dir: str, name: str, request: Request):
    base = _manage_dir(dir)
    if base is None:
        return {"ok": False, "error": "目录不支持"}
    name = Path(name).name
    if not re.fullmatch(r"[\w\u4e00-\u9fff.\- ]{1,80}", name):
        return {"ok": False, "error": "文件名不合法"}
    body = (await request.body()).decode("utf-8", errors="replace")
    (base / name).write_text(body, encoding="utf-8")
    return {"ok": True}


@app.post("/api/files/upload")
async def upload_file(dir: str, name: str, request: Request):
    base = _manage_dir(dir)
    if base is None:
        return {"ok": False, "error": "目录不支持"}
    name = Path(name).name
    if not re.fullmatch(r"[\w\u4e00-\u9fff.\- ]{1,80}", name):
        return {"ok": False, "error": "文件名不合法"}
    (base / name).write_bytes(await request.body())
    return {"ok": True, "size": (base / name).stat().st_size}


@app.delete("/api/files")
async def delete_file(dir: str, name: str):
    base = _manage_dir(dir)
    if base is None:
        return {"ok": False, "error": "目录不支持"}
    path = (base / Path(name).name).resolve()
    if path.is_relative_to(base) and path.exists():
        path.unlink()
    return {"ok": True}


@app.get("/api/backup")
async def backup():
    """打包 config.json + data/ 供下载。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(ROOT / "config.json", "config.json")
        for p in (ROOT / "data").rglob("*"):
            if p.is_file():
                z.write(p, f"data/{p.relative_to(ROOT / 'data')}")
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=anchor-backup.zip"},
    )


@app.post("/api/restore")
async def restore(request: Request):
    """从备份 zip 还原 config.json 与 data/。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(await request.body()))
    except Exception:
        return {"ok": False, "error": "不是合法的 zip 文件"}

    restored = []
    for member in zf.namelist():
        # 只允许 config.json / data / static 下的安全路径
        if not re.fullmatch(r"(config\.json|(data|static)/[\w\u4e00-\u9fff./\- ]+)", member):
            continue
        target = (ROOT / member).resolve()
        if not target.is_relative_to(ROOT) or target.is_dir():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(member))
        restored.append(member)

    # 还原后原地重载配置（各模块持有同一 dict 对象的引用）
    from . import config as config_module
    with open(ROOT / "config.json", "r", encoding="utf-8") as f:
        new_cfg = json.load(f)
    config_module.CONFIG.clear()
    config_module.CONFIG.update(new_cfg)
    pipeline.memory.per_user_interval = CONFIG["reply"].get("per_user_interval", 8.0)
    return {"ok": True, "restored": restored}
