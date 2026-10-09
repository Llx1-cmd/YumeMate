# 优香 AI 聊天系统 - YuukaChat

基于 Streamlit + FastAPI + Ollama + GPT-SoVITS 的二次元风格本地 AI 角色扮演聊天应用，支持多角色切换、语音合成与实时日历。

## ✨ 特性

- 🎀 **二次元界面** - 粉紫渐变主题、校园背景、角色立绘
- 💬 **流式对话** - 逐字输出，多轮上下文
- 🤖 **本地推理** - Ollama + Qwen2.5:7b，无需联网
- 🔊 **语音合成** - GPT-SoVITS 日语 TTS，每角色独立音色权重
- � **多角色** - 优香（yuuka）/ 未花（mika），一键切换
- � **浮动日历** - 二次元风格日历面板，纯前端零重绘
- 😀 **表情输入** - 微信式表情选择器
- ⏰ **时间感知** - AI 能感知当前真实时间与日期

## 🚀 快速开始

### 前置要求

1. **Python 3.10+**
2. **Ollama** + `qwen2.5:7b` 模型（`ollama pull qwen2.5:7b`）
3. **GPT-SoVITS**（语音用；仅需聊天可不装）- 放置于项目根目录的 `GPT-SoVITS-v2pro-20250604/`，内含 `runtime/python.exe` 与预训练模型

### 安装步骤

```bash
pip install -r backend/requirements.txt
pip install streamlit
```

### 启动

**一键启动（推荐）**

双击 `start_all.bat`，自动拉起四个服务：

| 顺序 | 服务 | 端口 | 说明 |
|------|------|------|------|
| 1 | Ollama | 11434 | 本地 LLM 推理 |
| 2 | 后端 | 8000 | FastAPI 聊天/语音 API |
| 3 | GPT-SoVITS | 9880 | 语音合成（权重加载约 1 分钟） |
| 4 | 前端 | 8501 | Streamlit 界面 |

启动后浏览器访问 **http://localhost:8501**。停止服务 = 关闭对应命令行窗口。

**仅聊天（无语音）**

双击 `start.bat`（只起后端 + 前端）。

## 📁 项目结构

```
YuukaChat/
├── frontend/
│   └── streamlit_app.py        # Streamlit 主程序（界面/日历/语音开关）
├── backend/
│   ├── main.py                 # FastAPI 路由（/api/chat、/api/tts-* 等）
│   ├── config.py               # 服务地址/端口配置
│   ├── requirements.txt
│   └── services/
│       ├── llm_service.py      # Ollama 调用 + 时间感知注入
│       ├── tts_service.py      # GPT-SoVITS 调用 + 角色权重切换
│       └── character_service.py# 角色配置加载
├── characters/
│   ├── yuuka/                  # 优香：character.json + reference.wav + 立绘
│   └── mika/                   # 未花：character.json + reference.wav + 立绘
├── GPT-SoVITS-v2pro-20250604/  # GPT-SoVITS 框架（gitignore，需自行放置）
├── cache/                      # 运行时缓存（gitignore）
├── start_all.bat               # 一键启动（含语音）
├── start.bat                   # 精简启动（仅聊天）
└── CHANGELOG.md                # 变更日志
```

## 🎨 技术栈

- **前端** - Streamlit 1.63+（Python 单文件，components.v1.html 注入日历/语音开关交互）
- **后端** - FastAPI + Uvicorn
- **LLM** - Ollama + Qwen2.5:7b
- **TTS** - GPT-SoVITS v2pro（角色级权重切换）
- **角色配置** - JSON（人设 prompt / 模型 / 参考音频 / TTS 权重路径）

## 🔧 配置说明

### 服务地址（`backend/config.py`）

```python
OLLAMA_BASE_URL = "http://localhost:11434"
BACKEND_PORT = 8000
```

### 角色配置（`characters/<角色>/character.json`）

每个角色独立配置：人设 prompt、Ollama 模型名、参考音频文本、TTS 权重路径（相对项目根目录）。新增角色只需在 `characters/` 下建目录并填好 `character.json`，重启后端即可。

## 📝 使用说明

1. **聊天** - 底部输入框输入文字，点发送按钮（无回车发送）
2. **表情** - 输入框右侧 😀 按钮展开表情面板
3. **语音** - 角色信息区 🔊 开关，开启后 AI 回复自动配音
4. **角色切换** - 界面角色区切换，语音权重自动跟随
5. **日历** - 角色信息区 📅 按钮展开浮动日历

## 🎯 下一步计划

- [ ] **群聊** - 多角色同台对话、角色间互动
- [ ] **记忆系统** - 长期记忆持久化与召回

## ❓ 常见问题

### Q: 启动后没有语音？
A: GPT-SoVITS 权重加载约 1 分钟，期间聊天正常但语音不可用，稍等即可。

### Q: AI 回复很慢？
A: 首次推理需加载模型（约 4.7GB），后续会快。取决于 GPU/CPU 性能。

### Q: 如何新增角色？
A: 在 `characters/` 下新建目录，放入 `character.json`（参考现有角色）、`reference.wav`（参考音频）、立绘图片，重启后端。

## 📄 License

MIT License
