# suisui

> 一个能**看图、看视频、联网搜索、带长期记忆**的本地 AI 智能体，基于 LangGraph 构建。
> 支持桌面 GUI 和 Web 网页两种界面，可一键切换云端 DeepSeek / 本地 Ollama 模型。

<p align="center">
  <img src="docs/screenshot-gui.png" width="620" alt="suisui GUI">
</p>

---

## ✨ 特性

| 能力 | 说明 |
|------|------|
| 🧠 **LangGraph 架构** | State / Node / Edge 图式编排，工具调用自动循环 |
| 🖼️ **看图** | 本地视觉模型（Qwen2.5-VL）描述图片内容、识别文字 |
| 🎬 **看视频** | 自动抽帧 + 逐帧识别，输出视频内容描述 |
| 🌐 **联网搜索** | 必应搜索 + 网页正文提取，**无需任何 API Key** |
| 💾 **长期记忆** | SQLite 持久化，关掉再开还记得；自动去重、自动摘要压缩 |
| 🔀 **双引擎** | 云端 DeepSeek（强）↔ 本地 Ollama（免费离线），界面一键切换 |
| 🖥️ **双界面** | 桌面 tkinter GUI + 浏览器 Web 界面（手机也能用） |
| 🔒 **隐私优先** | 本地模型模式下完全离线，数据不出电脑 |

---

## 📦 内置工具（8 个）

| 工具 | 作用 |
|------|------|
| `get_time` | 获取当前日期时间 |
| `calculate` | 数学计算（带注入防护） |
| `web_search` | 必应联网搜索 |
| `open_url` | 打开网页并提取正文 |
| `look_at_image` | 用视觉模型描述图片 |
| `look_at_video` | 抽帧识别视频内容 |
| `remember` | 记住一件重要的事 |
| `recall` | 回忆之前记住的事 |

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

复制 `config.example.json` 为 `config.json`，填入你的 API Key：

```bash
cp config.example.json config.json
```

```jsonc
{
  "DEEPSEEK_API_KEY": "sk-你的key",     // 必填（云端模式）
  "MODEL": "deepseek-chat",
  "USE_LOCAL": false,                   // true = 用本地模型
  "LOCAL_MODEL": "qwen2.5:7b"
}
```

### 3. 运行

**桌面版**（双击或命令行）：
```bash
python agent_gui.py
```

**Web 版**（浏览器访问）：
```bash
python server.py 8000
# 打开 http://127.0.0.1:8000
```

**命令行版**：
```bash
python agent_demo.py
```

---

## 🎨 视觉能力（可选）

看图/看视频需要本地视觉模型，用 [Ollama](https://ollama.com) 跑：

```bash
ollama pull qwen2.5vl:3b     # 3.2GB，快
# 或
ollama pull qwen2.5vl:7b     # 6GB，更准
```

然后在 `config.json` 里指定：
```json
{
  "VISION_MODEL": "qwen2.5vl:3b",
  "VISION_BASE_URL": "http://127.0.0.1:11434"
}
```

> 💡 不装视觉模型也不影响其他功能，只会让 `look_at_image` / `look_at_video` 不可用。

---

## 🔀 双引擎切换

界面左上角有个按钮，点一下即可切换：

- **云端 DeepSeek** — 智商高，需要 API Key，按 token 计费
- **本地 Ollama** — 免费离线，7B 模型智商略低但足够日常

对应配置：

```json
{
  "USE_LOCAL": true,
  "LOCAL_MODEL": "qwen2.5:7b",
  "LOCAL_BASE_URL": "http://127.0.0.1:11434/v1"
}
```

---

## 🌐 Web 版 & 局域网访问

```bash
python server.py 8000
```

| 谁 | 地址 |
|---|---|
| 本机 | `http://127.0.0.1:8000` |
| 同局域网 | `http://<你的IP>:8000` |
| 手机 | 同上（需同一 WiFi） |

**让别人访问需要放行防火墙**（管理员权限）：
```powershell
New-NetFirewallRule -DisplayName "suisui Web" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

**加访问口令**（公网暴露时强烈建议）：
```json
{ "WEB_TOKEN": "你的密码" }
```

---

## 🧠 记忆系统

基于 SQLite，三个表：

| 表 | 存什么 |
|---|---|
| `messages` | 全部对话记录 |
| `facts` | 记住的事实（"用户叫往尘"） |
| `summaries` | 自动压缩的对话摘要 |

- 对话超过 30 条自动总结旧内容，上下文永不爆
- 事实自动去重
- 删除 `memory.db` 即可清空记忆

---

## 🏗️ 架构

```
用户输入
   ↓
agent_demo.chat()
   ↓
┌─────────────────────────────────┐
│  LangGraph                       │
│                                  │
│  [agent] ──有tool_calls──> [tools]│
│     ↑                        │   │
│     └────────────────────────┘   │
│     │                            │
│     └──无tool_calls──> END       │
└─────────────────────────────────┘
   ↓
存记忆 → 自动摘要 → 返回
```

**文件结构**：

```
suisui/
├── agent_demo.py      # 核心：LangGraph 图 + 8个工具 + 记忆集成
├── agent_gui.py       # 桌面 GUI（tkinter，高DPI适配）
├── server.py          # Web 服务（零依赖，http.server）
├── vision.py          # 视觉模块（图片/视频识别）
├── web_tools.py       # 联网工具（必应搜索 + 网页提取）
├── memory.py          # 记忆系统（SQLite）
├── config.example.json
├── requirements.txt
└── tests/selftest.py  # 15 项自测
```

---

## 🧪 自测

```bash
python tests/selftest.py
```

会测试全部 8 个工具、记忆系统、端到端对话、Web 服务，共 15 项。

---

## 📋 环境要求

- Python 3.10+
- Windows / macOS / Linux
- 视觉模型需要 [Ollama](https://ollama.com)（可选）
- 显存 4GB+ 可跑 3B 视觉模型，8GB+ 可跑 7B

---

## 📄 License

MIT
