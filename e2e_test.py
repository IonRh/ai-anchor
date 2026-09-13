"""端到端自测：WS 监听 + 模拟直播事件，验证全链路。服务启动后直接 python e2e_test.py。"""
import asyncio
import json
import sys

import httpx
import websockets

BASE = "http://127.0.0.1:8000"
# 需要收齐的事件类型
REQUIRED = {"reply", "blocked", "welcome", "gift_thanks", "follow_thanks",
            "points", "song", "song_play", "ratelimited", "filtered", "like_thanks"}


async def send(client: httpx.AsyncClient, **body):
    r = await client.post(f"{BASE}/api/test_event", json=body)
    assert r.json()["ok"], r.text


async def main():
    events = []
    async with websockets.connect("ws://127.0.0.1:8000/ws") as ws:
        async with httpx.AsyncClient(timeout=60) as client:
            # 临时放大队列超时，避免 TTS 抖动导致队尾事件被丢弃；结束后还原
            await client.post(f"{BASE}/api/settings", json={"reply": {"queue_timeout": 120}})
            await send(client, type="danmu", username="小明", text="主播你好呀")       # → reply（兜底）
            await send(client, type="danmu", username="老王", text="加微信聊")         # → blocked
            await send(client, type="enter", username="小红")                          # → welcome
            await send(client, type="gift", username="小红", gift_name="火箭")         # → gift_thanks
            await send(client, type="like", username="小红")                           # 点赞计数
            await send(client, type="like", username="小红")
            await send(client, type="like", username="小红")
            await send(client, type="like", username="小红")
            await send(client, type="like", username="小红")                           # 累计 5 赞 → like_thanks
            await send(client, type="danmu", username="小明2", text="主播谢谢啦")      # → 关键词回复（reply, source=keyword）
            await send(client, type="follow", username="小红")                         # → follow_thanks
            await send(client, type="danmu", username="小红", text="签到")             # → points
            await send(client, type="danmu", username="小红", text="我的积分")         # → points
            await send(client, type="danmu", username="小明", text="点歌 test_song")   # → song + song_play
            await send(client, type="danmu", username="小刚", text="今天聊什么")       # → reply
            await send(client, type="danmu", username="小刚", text="再来一句")         # → ratelimited
            await send(client, type="danmu", username="新人", text="打个广告啦")       # → filtered（内容规则）
            await send(client, type="like", username="小刚")                           # 点赞计数
            await send(client, type="fanclub", username="小刚")                        # 计数

            try:
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                    events.append(msg)
                    got = {e["type"] for e in events}
                    if REQUIRED <= got:
                        break
            except asyncio.TimeoutError:
                pass

    got = {e["type"] for e in events}
    missing = REQUIRED - got
    print("收到事件:", sorted(got))
    assert not missing, f"缺少事件: {missing}"

    reply = next(e for e in events if e["type"] == "reply")
    kw_reply = next((e for e in events if e["type"] == "reply" and e.get("source") == "keyword"), None)
    song_play = next(e for e in events if e["type"] == "song_play")
    points = [e for e in events if e["type"] == "points"]
    rate = next(e for e in events if e["type"] == "ratelimited")
    filtered = next(e for e in events if e["type"] == "filtered")
    assert kw_reply is not None, "关键词回复未触发"
    assert kw_reply["text"] in ("不客气呀 " + kw_reply["username"], "小意思啦，常来玩"), \
        f"关键词回复内容异常: {kw_reply['text']}"

    async with httpx.AsyncClient(timeout=60) as client:
        if reply.get("audio_url"):
            a1 = await client.get(f"{BASE}{reply['audio_url']}")
            assert a1.status_code == 200 and len(a1.content) > 1000, "回复音频下载失败"
        else:
            print("（TTS 处于熔断期，回复无音频，跳过音频校验）")
        a2 = await client.get(f"{BASE}{song_play['audio_url']}")
        assert a2.status_code == 200 and len(a2.content) > 1000, "歌曲音频下载失败"

    # ---- 中控台管理接口 ----
    async with httpx.AsyncClient(timeout=60) as client:
        # 状态：计数应包含 like/fanclub
        st = (await client.get(f"{BASE}/api/console/status")).json()
        assert st["counters"]["like"] >= 1 and st["counters"]["fanclub"] >= 1, st
        # 启用AI回复开关往返
        r = await client.post(f"{BASE}/api/ai_reply", json={"enabled": False})
        assert r.json()["enabled"] is False
        r = await client.post(f"{BASE}/api/ai_reply", json={"enabled": True})
        assert r.json()["enabled"] is True
        # 设置读取 + 保存（greet 模板热更新）
        cfg = (await client.get(f"{BASE}/api/settings")).json()
        assert "llm" in cfg and "tts" in cfg
        r = (await client.post(f"{BASE}/api/settings",
             json={"greet": {"entrance_templates": ["测试欢迎 {username}"]}})).json()
        assert r["ok"], r
        cfg = (await client.get(f"{BASE}/api/settings")).json()
        assert cfg["greet"]["entrance_templates"] == ["测试欢迎 {username}"]
        # 还原模板，避免污染配置
        r = (await client.post(f"{BASE}/api/settings",
             json={"greet": {"entrance_templates": ["欢迎 {username} 进入直播间", "欢迎新来的 {username}"]}})).json()
        assert r["ok"]
        # 实时话术 → manual 播报事件
        await client.post(f"{BASE}/api/speak", json={"text": "中控台测试发言"})
        # 文件管理：新建/读取/删除话术
        r = (await client.post(f"{BASE}/api/files/content?dir=trends&name=e2e文案.txt",
             content="测试文案内容")).json()
        assert r["ok"], r
        c = (await client.get(f"{BASE}/api/files/content?dir=trends&name=e2e文案.txt")).json()
        assert c["content"] == "测试文案内容"
        r = await client.delete(f"{BASE}/api/files?dir=trends&name=e2e文案.txt")
        assert r.json()["ok"]
        # 备份下载
        b = await client.get(f"{BASE}/api/backup")
        assert b.status_code == 200 and b.content[:2] == b"PK", "备份 zip 无效"
        # 测试回复路由诊断
        d = (await client.post(f"{BASE}/api/test_reply",
             json={"text": "谢谢主播", "username": "路人"})).json()
        assert d["action"] == "keyword" and d.get("reply"), d
        d = (await client.post(f"{BASE}/api/test_reply", json={"text": "打个广告啦"})).json()
        assert d["action"] == "filtered", d
        d = (await client.post(f"{BASE}/api/test_reply", json={"text": "签到"})).json()
        assert d["action"] == "integral", d
        d = (await client.post(f"{BASE}/api/test_reply", json={"text": "今天天气不错"})).json()
        assert d["action"] in ("llm", "ratelimited", "ai_disabled"), d
        # 消息持久化：弹幕与 AI 回复应已入库，刷新可回看
        h = (await client.get(f"{BASE}/api/messages?limit=200")).json()
        assert h["ok"] and h["messages"], "消息历史为空"
        chat = next((m for m in h["messages"] if m["type"] == "chat" and m["content"] == "主播你好呀"), None)
        assert chat and "主播你好呀" in (chat["ai_reply"] or ""), "回复未持久化"
        # 拉取模型列表（未配置 key 时应优雅报错）
        r = (await client.get(f"{BASE}/api/llm/models")).json()
        assert "ok" in r, r
        print("模型拉取:", r.get("error") or f"{len(r.get('models', []))} 个模型")

    # manual 播报事件（在 WS 里等待）
    async with websockets.connect("ws://127.0.0.1:8000/ws") as ws:
        async with httpx.AsyncClient(timeout=60) as client:
            await client.post(f"{BASE}/api/speak", json={"text": "中控台测试发言"})
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                events.append(msg)
                if msg["type"] == "manual":
                    break

    print("回复文本:", reply["text"])
    print("签到/积分播报:", [e["text"] for e in points])
    print("限流等待秒数:", rate["wait"])
    print("歌曲文件:", song_play["audio_url"], len(a2.content), "bytes")
    # 还原队列超时配置
    async with httpx.AsyncClient(timeout=60) as client:
        await client.post(f"{BASE}/api/settings", json={"reply": {"queue_timeout": 25}})
    print("E2E PASS")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
