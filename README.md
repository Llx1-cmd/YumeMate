# 优香 AI 聊天系统 - YuukaChat

一个基于 React + FastAPI 的二次元风格 AI 聊天应用，使用本地 Ollama Qwen 模型驱动。

## ✨ 特性

- 🎀 **二次元界面** - 粉紫渐变主题，流畅动画效果
- ⚡ **实时对话** - WebSocket 流式输出，逐字显示
- 🤖 **本地 AI** - 使用 Ollama + Qwen2.5:7b 模型
- 📱 **响应式设计** - 适配桌面、平板、手机
- 🔧 **前后端分离** - 易于扩展和维护

## 🚀 快速开始

### 前置要求

1. **Python 3.10+** - 后端服务
2. **Node.js 18+** - 前端开发
3. **Ollama** - 本地 LLM 运行时（已安装）
4. **Qwen2.5:7b 模型** - 已配置

### 安装步骤

#### 1️⃣ 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
```

#### 2️⃣ 安装前端依赖

```bash
cd frontend
npm install
```

#### 3️⃣ 启动服务

**方式一：使用启动脚本（推荐）**

```bash
# Windows
双击 start.bat
```

**方式二：手动启动**

```bash
# 终端1：启动后端
cd backend
python main.py

# 终端2：启动前端
cd frontend
npm run dev
```

#### 4️⃣ 访问应用

打开浏览器访问：**http://localhost:5173**

## 📁 项目结构

```
YuukaChat/
├── backend/                 # Python 后端
│   ├── main.py             # FastAPI 主程序
│   ├── config.py           # 配置文件
│   ├── requirements.txt    # Python 依赖
│   └── services/
│       └── llm_service.py # Ollama 调用封装
│
├── frontend/               # React 前端
│   ├── src/
│   │   ├── components/     # UI 组件
│   │   ├── hooks/          # React Hooks
│   │   ├── styles/         # 样式文件
│   │   └── types/          # TypeScript 类型
│   └── package.json        # Node.js 依赖
│
└── start.bat               # Windows 启动脚本
```

## 🎨 技术栈

### 后端
- **FastAPI** - 高性能 Web 框架
- **WebSocket** - 实时双向通信
- **Ollama** - 本地 LLM 推理引擎
- **Qwen2.5:7b** - 通义千问大模型

### 前端
- **React 18** - UI 框架
- **TypeScript** - 类型安全
- **Vite** - 构建工具
- **Ant Design** - UI 组件库
- **Framer Motion** - 动画库

## 🔧 配置说明

### 后端配置 (`backend/config.py`)

```python
OLLAMA_BASE_URL = "http://localhost:11434"  # Ollama 地址
OLLAMA_MODEL = "qwen2.5:7b-instruct-q4_K_M"  # 模型名称
BACKEND_PORT = 8000  # 后端端口
```

### System Prompt 修改

编辑 `backend/config.py` 中的 `SYSTEM_PROMPT` 可以修改优香的：

- 性格特点
- 说话风格
- 回复长度
- 行为规范

## 📝 使用说明

1. **发送消息**
   - 在底部输入框输入文字
   - 按 Enter 或点击发送按钮

2. **查看回复**
   - AI 回复会逐字流式显示
   - 显示"正在输入..."动画指示器

3. **多轮对话**
   - 自动维护对话上下文
   - 支持连续多轮交互

## 🎯 下一步计划

- [ ] Phase 2: 对话历史持久化 + 多会话管理
- [ ] Phase 3: 语音功能（录音 + TTS）
- [ ] Phase 4: 3D VRM 角色展示（Three.js）

## ❓ 常见问题

### Q: 前端无法连接后端？
A: 确保：
1. 后端已启动（终端显示 `Uvicorn running on 127.0.0.1:8000`）
2. Ollama 服务已运行（`ollama serve`）
3. 浏览器控制台无报错

### Q: AI 回复很慢？
A: 这是正常的，取决于：
1. 你的 GPU/CPU 性能
2. 模型大小（7B 参数）
3. 首次加载需要初始化时间

### Q: 如何修改界面颜色？
A: 编辑 `frontend/src/styles/theme.ts` 中的配色方案。

## 📄 License

MIT License

---

**开发者提示：** 这是一个教学演示项目，适合学习前后端分离开发、WebSocket 实时通信、以及 AI 应用集成。
