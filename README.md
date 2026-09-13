# AI 主播后端 Demo

FastAPI + B 站弹幕 + LLM + TTS 的 AI 虚拟主播后端。
链路：**弹幕/直播事件 → 违禁词过滤 → LLM 回复 → TTS 合成 → WebSocket 推送 → 网页/OBS 播放**。

## 功能清单

- **弹幕互动**：B 站弹幕实时监听（bilibili-api），违禁词/长度过滤，LLM 回复（OpenAI 兼容接口：
  DeepSeek/GLM/Qwen 等），未配置 key 时自动兜底回复
- **关键词回复（优先于 AI）**：命中关键词直接用预置话术回复，不受限流影响；支持每规则多条
  关键词/多条随机回复、`re:` 正则、`*` 通配、`{username}` 变量；控制台可视化编辑
- **触发顺序**：关键词回复优先 → 其次才进入 AI 过滤、限流和回复生成（与商业直播助手一致）
- **AI 触发过滤规则**：内容/用户名两组规则（支持通配符与 `re:` 正则），只影响是否触发 AI，
  不影响关键词回复和弹幕本身显示；限流/丢弃/过滤在前端标注在原弹幕行，不再重复占行
- **直播事件**：进场欢迎（INTERACT_WORD）、礼物感谢（SEND_GIFT，按金额算积分）、
  关注感谢（USER_TOAST_MSG）、感谢点赞（累计达标触发）
- **回复质量**：每用户多轮上下文记忆、按用户限流（默认 8 秒）、单队列顺序播出、
  排队超时自动丢弃、LLM 输出二次违禁词过滤
- **定时播报**：报时（{time}）、感谢在看人数（{user_num}，读 B 站在线人数）、自定义话术，
  间隔支持随机范围 `interval_range: [最小, 最大]`
- **动态文案**：`data/trends/` 下 txt 轮播朗读，可让 LLM 改写去重
- **点歌**：弹幕 `点歌 xxx` / `取消点歌` / `随机点歌`，匹配 `data/songs/` 下的音频文件播放
- **积分签到**：`签到`/`打卡` 得分、`我的积分` 查询，进场/礼物自动加分，SQLite 持久化
- **多平台**：`platform` 可切 `bilibili` / `douyin`；抖音通过外部弹幕源 HTTP 接口接入
  （约定 JSON 格式见 `app/danmu/douyin.py`，可用原 meng-yun-ai 的弹幕源程序）
- **语音**：edge-tts（免 GPU）或 GPT-SoVITS（api_v2，自定义音色），engine 一键切换，
  GPT-SoVITS 失败自动回退 edge
- **推流**：OBS 一键拉起（`/api/obs/start`），数字人/字幕 overlay 页
  （`/overlay.html`，OBS 浏览器源加载，CSS 形象 + 口型动画，可选 Live2D：`?model=<模型json>`）
- **消息持久化**：所有直播事件与 AI 回复写入 SQLite（`data/messages.db`，保留最近 5000 条），
  页面刷新后自动回看历史；`GET /api/messages` 可分页拉取
- **手机端 App（PWA）**：`/mobile.html` —— 手机浏览器打开后「添加到主屏幕」即像 App 一样使用：
  启停监听、实时消息流、实时话术（让主播说话）、**实时播放主播语音**（可开关）、AI 回复开关。
  手机与电脑需同一局域网，用电脑的内网 IP 访问（如 `http://192.168.x.x:8000/mobile.html`，
  启动服务时需把 host 改为 `0.0.0.0`）
- **AI 回复拉取模型**：AI回复页一键从 LLM 服务拉取可用模型列表（OpenAI 兼容 `/models`），
  点选即填入
- **调试**：`/api/test_event` 模拟弹幕/进场/礼物/关注/点赞/粉丝团，`/api/tts?text=` 手动测朗读，
  `/api/test_reply` 诊断弹幕路由（关键词/LLM/过滤/限流），`e2e_test.py` 一键端到端自测
- **中控台**（对照商业直播助手形态）：多 Tab 控制台 —— 直播中控台（运行状态：连接/当前观看/
  累计观看/在线观众/各事件计数/表情统计；实时消息流表格：序号/时间/用户/内容/AI回复列，
  按聊天/礼物/点赞/关注/进场/粉丝团筛选，启用AI回复开关，清空列表）、直播平台接入
  （B站直连，抖音/视频号/淘宝/美团/快手经弹幕源）、AI回复/AI语音设置（即时生效）、
  播报回复话术编辑、音频话术（动态文案编辑/立即朗读）、实时话术（手动说话）、
  音频管理（点歌库上传/删除/试听）、备份/还原（config+data 打包下载/上传恢复）

## 运行

```bash
cd ai-anchor
uv venv
uv pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 进入控制台：填直播间号（默认 `21452505`）点「开始监听」，
弹幕会被 AI 回复并朗读；面板上可直接模拟进场/礼物/关注/弹幕事件。
端到端自测：`.venv\Scripts\python.exe e2e_test.py`（服务需在运行）。

## 配置（config.json）

| 段 | 说明 |
|---|---|
| `platform` | `bilibili` 或 `douyin` |
| `bilibili` / `douyin` | 房间号；抖音需本地跑弹幕源服务（`source_url`） |
| `llm` | OpenAI 兼容接口，`api_key` 留空走兜底回复；可用环境变量 `ANCHOR_LLM_API_KEY` 注入 |
| `reply` | `max_turns` 多轮记忆轮数 / `per_user_interval` 用户限流秒数 / `queue_timeout` 排队超时秒数 / `queue_max` 队列洪峰保护上限 |
| `tts` | `engine`: `edge` 或 `gptsovits`；`gptsovits` 段配参考音频（api_v2 服务：`python api_v2.py -a 0.0.0.0 -p 9880`） |
| `greet` | 进场/礼物/关注话术模板，`{username}` `{gift_name}` `{gift_num}` 占位 |
| `integral` | 积分开关、分值、触发指令、SQLite 路径 |
| `song` | 点歌触发词与歌曲目录（支持 mp3/wav/flac/m4a，文件名模糊匹配） |
| `schedule` / `trends` | 定时播报项与动态文案目录、改写开关 |
| `streaming.obs` | `enable` 后可用 `/api/obs/start` 拉起 OBS（`path` 指向 obs64.exe） |

## 推流玩法（数字人直播）

1. 启动本服务并开始监听；
2. OBS 添加**浏览器源**：`http://127.0.0.1:8000/overlay.html`
   （要 Live2D 形象则 `overlay.html?model=<模型json的URL>`，需模型可公网访问）；
3. 添加音频捕获（虚拟声卡，如 VB-Cable），在 OBS 混音器里选浏览器源声音；
4. OBS 设置 → 推流，填平台的 RTMP 地址，开始推流。
   控制台点「启动 OBS」可自动拉起 OBS 程序。

## 手机端 App

三种形态，按需选择：

1. **PWA（推荐，零安装依赖）**：手机浏览器打开 `http://<电脑内网IP>:8000/mobile.html`，
   菜单「添加到主屏幕」即得全屏 App（服务端 host 需改为 `0.0.0.0`）。
2. **安卓 APK**：`android-app/` 是一个 WebView 壳工程（首次启动填服务器地址，记住后自动进手机页，
   屏幕常亮、连接失败可重新配置）。本机无需任何安卓工具——把项目推到 GitHub 后，
   Actions 工作流 `.github/workflows/build-apk.yml` 会自动编译，在仓库
   **Actions → Build Android APK → Artifacts** 下载 `ai-anchor-apk`，传到手机安装即可
   （debug 签名，安装时允许"未知来源"）。
3. 电脑端控制台（`/`）功能最全，手机端与电脑端实时同步。

## 结构

```
app/
  main.py               # FastAPI 路由
  pipeline.py           # 核心管线：事件路由 / 单队列 / 限流 / 超时丢弃
  ws.py                 # WebSocket 广播
  memory.py             # 多轮上下文记忆 + 按用户限流
  config.py             # 读取 config.json
  danmu/bilibili.py     # B 站弹幕（弹幕/进场/礼物/关注事件）
  danmu/douyin.py       # 抖音弹幕源适配器（轮询外部 HTTP 服务）
  filter/badwords.py    # 违禁词 + 长度过滤
  llm/openai_compat.py  # OpenAI 兼容对话（含历史上下文）
  tts/                  # 引擎调度 + edge-tts + GPT-SoVITS
  features/
    greet.py            # 欢迎/感谢话术
    integral.py         # 积分签到（SQLite）
    songs.py            # 点歌匹配
    schedule.py         # 定时播报 + 动态文案
  streaming/obs.py      # OBS 拉起与检测
static/index.html       # 控制台（事件模拟、实时日志、自动播放）
static/overlay.html     # OBS 浏览器源 overlay（数字人形象 + 字幕）
e2e_test.py             # 端到端自测
```

## 已验证

- B 站弹幕匿名连接认证成功；弹幕 → 拦截/回复 → TTS → WS 推送全链路
- 进场/礼物/关注/点赞/粉丝团/签到/积分查询/点歌/限流事件 E2E 全部通过（`e2e_test.py`）
- 定时播报（报时项）在监听启动后按配置触发
- 中控台管理接口（状态/设置热保存/启用AI回复开关/实时话术/文件管理/备份zip）E2E 通过
- 消息持久化：事件与 AI 回复入库，`/api/messages` 回看，控制台与手机端刷新后历史自动加载
- 手机端 PWA（390×844 视口实测）：控制条/状态/语音开关/实时话术/历史消息正常渲染
- 模型拉取：mock OpenAI 兼容 `/models` 实测返回模型列表；未配置 key 时优雅报错
- 浏览器实测控制台：布局渲染、Tab 切换、表单回填、消息流实时更新与 AI 回复列回填均正常
- 启动监听失败（如房间号错误）即时返回具体错误；平台可在启动时热切换，无需重启
- 长播保护：TTS 缓存自动清理（保留 300 个）、记忆/限流表按用户数封顶（300）、队列满自动丢弃、观看人数查询带 10 秒缓存
- TTS 熔断降级：单次合成硬超时 20 秒（防网络挂起卡死队列），连续失败 3 次熔断 60 秒，期间回复照常推送（纯文字）
- 启停交互：中控台顶部控制条，启停秒级返回、失败原因内联显示（如"房间不存在"）、按钮状态与连接状态联动
- 抖音适配器对 mock 弹幕源的事件解析（danmu/enter/gift/follow）通过
- GPT-SoVITS 引擎不可达时自动回退 edge-tts
- edge-tts 偶发 `NoAudioReceived` 已加 3 次重试

## 下一步

- 手机控制端 App（Flutter/uni-app，配置 + 监控）
- 云端托管推流、多直播间实例化
- GPT-SoVITS 音色训练脚本接入
