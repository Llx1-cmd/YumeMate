# 开发日志 / 更新公告

本文件记录开发过程中遇到的错误、原因与解决方法（区别于 README.md，README 面向使用者介绍用法，本文件面向开发者记录排错过程）。

---

## 2026-09-10

### 1. 启动报错：无法加载角色
- **问题**：双击 `start.bat` 启动后，界面显示「⚠️ 无法加载角色」/「❌ 无法加载角色列表，请确认后端是否启动」。
- **原因**：`start.bat` 只启动了 Streamlit 前端，没有启动 FastAPI 后端。前端请求 `http://127.0.0.1:8000/api/characters` 连接失败，拿到空列表。
- **解决**：修改 `start.bat`，在启动前端前先单独开窗口启动后端，等待 3 秒后再启动前端：
  ```bat
  start "YuukaChat-Backend" cmd /k "cd backend && python -m uvicorn main:app --host 127.0.0.1 --port 8000"
  ```

### 2. 对话报错：Read timed out（120 秒）
- **问题**：发送消息后报错 `HTTPConnectionPool(host='127.0.0.1', port=8000): Read timed out. (read timeout=120)`。
- **原因**：CPU 占用过高，导致模型加载 / 推理变慢，超过前端 `streamlit_app.py` 中 `timeout=120` 秒的限制。
- **解决**：定位为 CPU 占用问题（已解决）。模型热加载后 30 token 约 2.4 秒，推理本身速度正常；若再次偶发超时，可将前端 `timeout=120` 调大。

### 3. 清理：删除无用启动脚本
- **问题**：项目根目录存在 3 个 .bat，功能重叠或已失效。
- **解决**：删除
  - `start-streamlit.bat`：与修复后的 `start.bat` 重复，且不启动后端。
  - `start-full.bat`：依赖已被移除的 React 前端（`frontend/` 下无 `src/` 与 `package.json`），`npm run dev` 会失败。
  - 保留 `start.bat` 作为唯一启动脚本。

### 4. 新增：微信式表情选择器
- **需求**：聊天输入框右侧加表情按钮，点击展开表情面板，类似微信。
- **调研**：PyPI 无专用 Streamlit emoji picker 组件（`st-emoji-picker` / `streamlit-emoji-picker` / `streamlit-emoji` 均不存在），GitHub 亦无成熟方案；`streamlit-extras` / `extra-streamlit-components` 不含该功能。
- **解决**：用 Streamlit 原生能力手搓（无需第三方库）。`frontend/streamlit_app.py` 中将 `st.chat_input` 换成 `st.text_input` + `st.popover("😀")` 表情按钮 + 「发送」按钮；`st.popover` 内用 `st.columns(8)` 渲染 8×5 共 40 个常用 emoji，点击追加到输入框末尾；新增 `_send_message` 共享发送逻辑、`_render_emoji_panel` 渲染表情网格。注意：回车不再直接发送，改为点「发送」按钮。

### 5. 修复：表情按钮上的 expand_more 回退文字
- **问题**：表情按钮（😀）上出现 `expand_more` 字样（点击展开后的表情面板本身正常）。
- **原因**：Streamlit 的 popover 展开箭头由 DynamicIcon 渲染成 `[data-testid="stIconMaterial"]`，依赖 Material Icons 图标字体连字；项目全局 CSS `* { font-family: 'Noto Sans SC' !important }` 覆盖了该字体，连字失效，图标退化成字面文字 `expand_more`。
- **解决**：在 CSS 中隐藏 `[data-testid="stIconMaterial"]`，与项目既有的「规避图标字体回退」处理方式一致。

---

## 2026-09-11

### 6. 表情输入框的回车发送与自动清空（回退自定义组件，改用纯原生方案 A）
- **问题**：为实现微信式表情输入框，先后尝试 `st.text_input` + `st.popover` 以及 `declare_component` 自定义组件两套方案，分别导致「① 回车发不了消息；② 发送后消息不清空」以及大量报错（`st.components.v1.html` 不支持 `key` 直接抛 TypeError、自定义组件 bug 多），最终全部回退。
- **原因**：Streamlit 框架硬限制——① 非 form 的 `st.text_input` 回车与失焦在前端走同一触发路径，无法区分「仅回车发送」；② `st.chat_input` 自带回车发送 + 自动清空，但无法在右侧挂表情按钮、也无法在光标处注入表情；③ `st.components.v1.html` 是纯 iframe（不支持 key/回传），`declare_component` 自定义组件虽能双向通信但坑多易错。
- **解决**：回退到纯 Streamlit 原生「方案 A」——恢复 `st.chat_input`（回车发送 + 发送后自动清空，框架原生、零 bug）；在输入框**上方**放 😀 表情按钮（`st.popover`），点表情追加到 `st.session_state._emoji_buf_{角色id}` 表情缓冲，上方实时预览（可一键清空）；发送时拼接「表情 + 文字」一起发送并清空缓冲。代价：表情不能插到光标处，只能"先选好表情再打字一起发"。表情按钮仍用 `st.popover`，故沿用第 5 条的 `stIconMaterial` 隐藏处理。

---

## 2026-09-14

### 7. 最终回退：表情按钮在输入框右侧的版本（方案 B）
- **问题**：方案 2（`declare_component` 自定义组件）在用户实际环境组件前端资源加载失败（`streamlit_app.chat_composer` 报 "having trouble loading"，疑为网络/proxy 障碍）；本地 playwright 端到端测试虽返回 200，但用户环境反复重启仍失败，遂不再深究。
- **决策**：用户最终回退到「方案 B」——表情按钮在**输入框右侧**、点表情直接进输入框，**放弃回车发送**改用「发送」按钮。
- **解决**：
  - 输入区改回 `st.text_input` + 右侧 😀 `st.popover` 表情按钮 + 「发送」按钮。
  - 表情追加用 `on_click=_append_emoji` 回调（在脚本运行前执行，可安全改写 widget key，规避 `StreamlitWidgetAlreadyInstantiatedError`）。
  - 发送用 `on_click=_prepare_send` 回调暂存待发文本并清空输入框，脚本主体读取 `_pending_send` 后调 `_send_message`，修复此前「发送后消息不清空」的 bug。
  - 清理 `declare_component` 声明、`import streamlit.components.v1` 及 `frontend/component/index.html`。
- **备注**：回车不可用是 `st.text_input` 框架限制（回车与失焦在前端走同一路径，无法区分），用户已接受改用「发送」按钮。

---

## 2026-09-15 ~ 2026-09-17

### 8. 前端 UI 美化（日系浅色二次元，参考 Avatar Chatbot 三轮迭代）
- **背景**：用户提供开源项目 Avatar Chatbot（React+Vite+Live2D）作设计参考，要求吸收其「角色成为视觉主体」的设计思路，但不用其 React/后端/Live2D/图片，项目仍保持 Streamlit + FastAPI。
- **第一轮（布局）**：确立日系浅色 + 左右两栏（左角色立绘区 / 右聊天区）；角色区只做 `character-container → character-image` 容器结构（未来替换 Live2D/3D）；消息气泡改为带三角尾巴；输入区保留方案 B 逻辑、只改视觉。
- **第二轮（视觉层次）**：从「白色卡片 Demo」向「角色陪伴感」演进——减少白色卡片感、角色区去边框/柔光/立绘贴底、面板半透明毛玻璃、header 两行并预留 ♡/🔊、侧边栏角色项显示在线状态。
- **第三轮（构图重构）**：解决「页面太白」——背景由近似纯白改为淡灰紫 `#ECE7EF`，白面板浮在灰紫底上形成层次；角色区重构为 `character-stage`（background-layer + background-overlay + character-container → character-image），背景图以后放 `assets/background/` 即可换场景；左右比例调 45:55；聊天区去掉卡片背景完全开放、消息气泡浮在背景上；Welcome State 改为「👋 + 你好呀，我是{角色名}～ + 今天想和我聊点什么？」；侧边栏群聊/语音改为文字占位、设置按钮去粉；建立颜色层次（基础灰紫 / 面板白 / 辅助淡紫淡蓝 / 强调粉 / 状态绿）。
- **约束**：全程未生成、未下载任何图片；未改后端/API/AI/TTS/聊天历史/表情/发送逻辑。

### 9. 修复：角色舞台 HTML 源码被直接显示（Markdown 空行打断 HTML 块）
- **问题**：立绘区出现一串 `<div class="background-overlay">…</div>` 源码直接显示在页面上，而非被渲染成舞台。
- **原因**：立绘区 HTML 原本用多行 f-string 书写，其中 `{bg_layer}`（背景层）在未放背景图时为空字符串，于是在 HTML 里产生一个**空行**；Streamlit 的 Markdown 解析遇到「HTML 标签后紧跟空行」会提前结束 HTML 块，空行之后的 `<div>` 被当作普通文本直接显示。
- **解决**：将立绘区与欢迎文案的 HTML 从「多行 f-string」改为**字符串拼接**（顶格、无空行），避免空行打断 HTML 块，同时规避缩进被误判为 Markdown 代码块的隐患。
---

## 2026-09-21

### 10. 修复：点表情 / 发消息时顶部 Header 闪烁
- **问题**：点击 emoji 或「发送」按钮时，顶部 header（角色名 / 在线状态）会「闪」一下（向上跳），但聊天背景、立绘、背景图不闪。
- **原因**（playwright 运行时实测，非 CSS 猜测）：底部输入区的 😀/发送按钮底部**固定在 y≈754px**（由舞台 `min-height:540px` + Header + 间距决定，与视口高度无关）。当浏览器视口高度 < 754px（窗口未最大化/有工具栏书签栏任务栏/DPI 缩放）时，按钮卡出 stMain 可视区；点击按钮 → 按钮聚焦 → 触发浏览器/Streamlit 滚动 stMain 把按钮滚进视口 → Header 被顶上去＝「闪」。实测按视口高度：800 滚 0、750 滚 4、720 滚 34、700 滚 275（滚到底）。背景图不闪是因为 `.global-background` 是 fixed 定位；立绘/聊天区同样位移但因区域大视觉不明显。
- **定位判断**：属「位置变化（滚动）」而非「本身重绘」——全程 MutationObserver **0 次 DOM 替换**、rAF 帧级采样 opacity/visibility/transform/animation **全程不变**、**0 次 animation/transition 事件**；且拦截 `Element.scrollIntoView` 为空（滚动不经过该 API），阻止 mousedown-focus 后滚动从 275→54px（确认聚焦参与）。
- **走过的弯路**：先误删 `.chat-header` 的 `backdrop-filter`（无意义），无效；再改 `.block-container` `padding-top:96→24px`，只把按钮从 826 移到 754，仍高于多数窗口实际视口，无效。
- **最终解决**：`.chat-header` 改 `position: fixed; top:40px; left:324px; right:24px; z-index:100` 脱离 stMain 滚动流（视觉位置不变）；`.block-container` `padding-top` 补 `110px`（24 + Header 86px 占位）补偿。无论 stMain 滚多远，Header 始终钉在 y=40 不动。
- **验证**：6 个视口（600/650/700/720/750/800）点 emoji + 发消息，Header top 值域恒 [40]（rAF 帧级采样），舞台 top=174 > Header bottom=112 零遮挡。

### 11. 立绘假白边 + 半透明白色圆角矩形 + 背景图太艳
- **白边根因**：`get_character_portrait` 查找 `frontend/assets/character/{id}.png/.jpg/.jpeg`；用户把透明底图放在 `frontend/assets/yuuka .jpeg`（assets 根目录 + 文件名含空格），前端找不到回退到白底头像 `avatar.jpeg`。解决：移到 `frontend/assets/character/yuuka.png`（character 子目录、无空格）。
- **半透明白色圆角矩形**：`.character-stage` 的 `background: rgba(255,255,255,0.16)` 与 `.background-overlay` 的白色渐变两个白色来源叠加，形成立绘背后的大白卡。解决：两者改 `transparent`，并移除 `.character-stage` 的矩形 `box-shadow`；保留 `.character-image img` 的 `drop-shadow` 让人物与背景分离；「在线」胶囊保留。
- **背景图太艳**：`.global-background` 原无 filter。解决：加 `filter: saturate(0.55) brightness(1.15) contrast(0.9)` 降艳提亮。
---

## 2026-09-22

### 12. 重构：输入区固定到底部 + 消息区独立滚动（彻底解决 Header 闪烁）
- **背景**：第 10 条的 `position: fixed` 方案被用户否决——它让 Header 固定悬浮、滚轮下滑时不跟随，属"结构问题"（用固定掩盖滚动，而非解决）。遂回退 fixed，恢复 Header 正常文档流。
- **真正根因（源码级定位）**：Streamlit 前端 `static/js/index.js` **重写了 `HTMLElement.prototype.focus`**——元素聚焦时若超出滚动容器视口，就主动 `scrollTo` 滚动容器把它带进视口。链条：点 😀/发送 → 按钮聚焦 → 按钮底部 y=754 超出视口（视口 < 754 时）→ Streamlit 自动滚 stMain → Header 被顶上去＝闪。padding、fixed 都没碰这个聚焦滚动，故修几轮仍在。
- **用户拍板方案**：固定输入区到底部 + 消息区独立滚动（聊天软件标准结构）。
- **实现**（`frontend/streamlit_app.py`）：
  - 版权 footer 改为仅首页/设置页显示（`if cid is None or cid == "settings"`），聊天页不占底部；
  - `.block-container` `padding-bottom` 160→16（去 Streamlit 默认大留白）；
  - `.character-stage`、`.chat-messages` 高度由固定 `min-height:540/500px` 改为 `calc(100vh - 230px)`（230 = padding-top 24 + Header 86 + 两栏间距 + 输入区 56 + padding-bottom 16 的实测总和），`min-height:320px` 保底；消息区 `overflow-y:auto` 在固定高度内独立滚动。
  - 结果：整页高度＝视口高、stMain 不再滚动 → 按钮永不超视口 → 聚焦不滚动 → Header 正常文档流且点按钮不闪。
- **验证（Playwright + PIL 像素级）**：视口 650/700/720/800 下整页溢出均 0、输入框 bottom=视口-16 贴底、Header top 恒 [40]；**PIL 对比点 emoji+发消息前后截图：Header 区域（y=40-112）差异占比 0.0000、最大像素差 0**（客观证明不闪）；首页 overflow=0 正常。
- **备注**：测试中"正在回复中"长时间不消失，是 Ollama 模型冷启动慢（`send_chat_message` timeout=120s），非代码问题。
### 13. 换方案：彻底移除顶部 Header，角色信息移到立绘上方（普通文档流）
- **背景**：Header 闪烁连续排查两天未彻底消除（用户实测仍闪），用户决定换设计方案——不再修 Header，直接移除顶部独立 Header。
- **实现**（`frontend/streamlit_app.py`）：
  - **删除**原顶部 Header 的 DOM（`render_chat_page` 里 `st.markdown(chat-header)`）与全部 `.chat-header` CSS，不留占位容器；
  - 新增 `.character-info`（角色名 + 副标题·在线 + ♡🔊），放在**左栏立绘舞台上方**，纯普通文档流（无 fixed/sticky/absolute）；
  - 高度偏移 `calc(100vh - 230px)` → `calc(100vh - 205px)`（去掉 Header 86px、加回角色信息约 54px，实测校准到整页溢出 0）；
  - **修复发送时页面跳动**：原 `st.spinner("正在回复中...")` 是独立元素、占 26px + 16px 间距 = 42px，出现/消失时把下方所有元素顶得上下跳。改为把"正在回复中"作为**消息区内部的一条气泡**（`.bubble.replying`），并把 `_do_send` 延迟到渲染之后再执行，使其不占额外高度。
- **验证（Playwright rAF 帧级 + PIL 像素级）**：视口 800/700 下，滚轮上下 + 点 emoji + 发消息 + 连发 2 条全程：角色信息 top 恒 [40]、舞台 top 恒 [133]、消息区 top 恒 [40]、scrollTop 恒 [0]、整页溢出恒 [0]；**PIL 对比发送前后：角色信息条（x=324-727,y=40-89）差异占比 0.0000、最大差 0**，左栏（x=0-640）全零差异，差异仅在右栏消息区（内容变化）。
---

## 2026-09-28

### 14. @st.fragment 隔离聊天交互区（彻底解决点击 widget 闪烁）
- **背景**：第 12/13 条之后闪烁仍未根除。用户实测收敛出规律：**展开 emoji 不闪；选 emoji、点发送（无论发送框有无内容）都闪**。共同点＝「改变 Streamlit widget 状态 / 触发 widget interaction」。据此确认根因是 **full-app rerun 路径**：任何 widget 交互都触发整页 rerun，使带白色背景的元素（角色信息卡片、😀 按钮）在 rerun 时被短暂重绘/露白＝闪烁。此前在 CSS 方向试过 box-shadow 去除、`translateZ(0)`、`background` 硬编码、`linear-gradient` 底、换底色、透明底等**全部无效**（因根因不在 CSS，而在 rerun 范围）。
- **用户拍板方案**：停止改 CSS、停止排查 GPU，用 `@st.fragment` 把聊天交互区隔离出来做最小化架构实验（不重构 UI）。
- **实现**（`frontend/streamlit_app.py`，Streamlit 1.63.0）：
  - 新增 `@st.fragment def render_chat_fragment(character_id, name)`，承载 **消息历史 + emoji + 输入框 + 发送按钮 + pending 处理**；
  - `render_chat_page` 保留 fragment 外内容（character-info / 校园背景 / 优香立绘），右栏 `col_chat` 内调用 fragment；
  - fragment 内发送完成后的 rerun 用 `st.rerun(scope="fragment")`，只 rerun fragment。
- **验证**：用户真实浏览器实测 **A 空发送 / B 正常发送 / C 只展开 emoji / D 选 emoji 四场景全部不闪** → 反证根因确为 full-app rerun 路径，方案成立并冻结。
- **同日修复其 UI 回归**：
  - **emoji 按钮不显示图标 + 发送按钮被截断成「发」**：fragment 把输入区从「横跨整页」移进右栏 `col_chat`，宽度减半，`st.columns([12,1,1.5])` 下 emoji 列仅约 37px（按钮 26px）装不下字形。修复：输入区比例 **`[12,1,1.5]` → `[11,2,3]`**（emoji 按钮 26→51px、发送按钮 41→82px 完整显示「发送」），并经 PIL 确认 emoji 黄色像素 39（正常渲染）。
  - 字体兜底：全局 `* { font-family: ... }` 列表追加 `'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji'`。
  - **character-info / 欢迎区恢复轻量半透明白背景**：`.character-info` → `rgba(255,255,255,0.65)`；`.welcome-box` → `rgba(255,255,255,0.6)` + 圆角，保持校园背景可见。均只改视觉，不动 fragment 结构。
- **纪律约束（用户下令）**：勿再改 fragment 结构、勿恢复全局 rerun、勿重建 fixed/sticky Header；backend `/api/chat`、Ollama、聊天逻辑、优香图片、校园背景文件均不得改。
- **未决**：真实浏览器中聊天页右侧仍有一条"白边"（首页无、全屏后消失、跟随浏览器主题变色）。已排除页面内原因（无滚动条、无横向溢出、无越界元素、背景图 right=视口、背景图右侧非白色）；下一步需用户在"白边可见"状态下做严格对照（同窗口切 `about:blank`）并量白边像素宽度以定位是浏览器窗口非页面区还是页面问题。
  - → 已于 2026-10-01 定位并修复，见第 15 条。

---

## 2026-10-01

### 15. 修复：聊天页右侧白边（object-fit 被 Streamlit 规则压成 scale-down）
- **问题**：聊天页右侧有一条贯穿全高的纯白竖条（首页无、F11 全屏后消失、颜色跟随浏览器主题），但 DOM 测量全部正常：无垂直/水平滚动条、`docScrollW = bodyScrollW = innerW`、无元素越界、`.global-background` 的 `right = viewport right` 且 `width = viewport width`、视口最右侧像素非白。**DOM 测量与肉眼所见不一致。**
- **走过的弯路**：
  - 曾怀疑 `stMain` 滚动条 —— 被证伪。**方法论教训：Chromium 的 overlay/thin 滚动条不占布局宽度，所以 `offsetWidth - clientWidth == 0` 不能证明"没有滚动条"。**
  - 曾怀疑 `.character-stage` / `.chat-messages` 的 `min-height: 320px` 在矮视口顶破 100vh —— 被证伪（`innerHeight 732 > 525`，未触发）。
  - 曾怀疑 `transform` / `filter` / `backdrop-filter` / `will-change` / `contain` 祖先劫持 fixed 定位 —— 被证伪（祖先循环无匹配，返回 `null`）。
  - **测量学陷阱（关键）**：用户每次贴的 Console 输出都是 `innerWidth 974 / innerHeight 732`，这个数字本身证明 **DevTools 是停靠着的**，视口被压到 974 CSS px，而白边只在宽视口出现 —— 于是每次测量都恰好落在"白边消失"的状态，导致长期"量不到"。
- **根因**：`.global-background` 的 computed `object-fit` 被 Streamlit 自带的高特异性规则（形如 `[data-testid="stMarkdownContainer"] img { object-fit: scale-down }`）压成了 **`scale-down`**，而源码声明的是 `cover`。`scale-down` 在图片大于盒子时**等价于 `contain`**，产生等比内缩留白。
  - **认知要点**：`getBoundingClientRect()` 量的是 `<img>` 的**元素盒子**（永远 100vw×100vh 全宽），留白发生在元素**内部**由 `object-fit` 决定 —— **DOM 几何永远看不到它**，只有像素和 computed `object-fit` 能暴露。
- **算式验证**（原图 3840×2095，比例 A = 1.8329；`scale-down` ≡ contain → 显示宽 = `min(视口宽, 视口高 × A)`）：

  | 状态 | 视口 (CSS px) | 视口高 × 1.8329 | 左右各留白 | 白边 |
  |---|---|---|---|---|
  | 最大化，DevTools 关闭 | 1536 × 733.6 | 1344.7 | **(1536−1344.7)/2 = 95.7** | ✅ 有 |
  | 最大化，DevTools 停靠右 | 974 × 732 | 1341.7 | 0 | ❌ 无 |
  | F11 全屏 | 1536 × 864 | 1583.6 | 0 | ❌ 无 |

  像素取证实测白边 = 119 物理px = **95.2 CSS px**，与算出的 95.7 吻合，且是 1px 硬切（非模糊/阴影）。
- **同时解释三个现象**：
  - **首页无**：[streamlit_app.py](file:///f:/YuukaChat/frontend/streamlit_app.py#L435-L446) 的 `if bg:` 分支才输出该 `<img>`，首页没有角色背景图。
  - **左侧也不见白边**：左边那 95.7px 被 **300px 宽的侧边栏**挡住，只有右边露出来。
  - **跟随浏览器主题变色**：`html, body { background: transparent !important }` 使留白区无任何元素绘制，露出浏览器默认画布色。
- **解决**：[streamlit_app.py](file:///f:/YuukaChat/frontend/streamlit_app.py#L549) 第 549 行 `object-fit: cover;` → **`object-fit: cover !important;`**，用 `!important` 压过 Streamlit 的规则。**未改** `width` / `height` / `100vw` / `background-size`，也未触碰禁改清单（`@st.fragment` / `rerun` / `chat fragment` / `st.columns` / `character-info` / `welcome box`）。
- **验证**：browser_use 子代理打开 http://localhost:8501 → 进入"早濑优香"聊天页 → `getComputedStyle(document.querySelector('.global-background')).objectFit` 返回 **`cover`**（期望值一致，`!important` 覆盖生效）；用户真实浏览器实测确认白边消失。

### 16. 侧边栏「角色」分组展开导致角色卡 / 😀 按钮闪烁（又是 full-app rerun）
- **问题**：点击左侧边栏「🎭 角色」分组的展开/收起按钮，主区左栏的角色卡 `.character-info` 与聊天区 😀 表情按钮会闪。
- **根因**：与第 14 条同一条路径。第 14 条只把「消息区 + 输入区」包成了 `@st.fragment`，**侧边栏不在其中**；而 `_render_sidebar_section()` 点击后调用的是 **`st.rerun()`（app 作用域）** → 整页 rerun → `main()` 从头上重跑、主区全部重绘 → 带半透明白底的角色卡与 😀 按钮在重绘瞬间露白＝闪。所以侧边栏的任何交互都会整页重跑。
- **解决**（`frontend/streamlit_app.py`）：
  - `render_sidebar()` 加 `@st.fragment`，整条侧边栏纳入 fragment 隔离；
  - `_render_sidebar_section()` 的 `st.rerun()` → **`st.rerun(scope="fragment")`**，展开/收起只重跑侧边栏；
  - 侧边栏里的**页面跳转按钮**（角色切换 / 设置 / 返回主页）**保持 `st.rerun()` 不动** —— 切页本就需要整页重跑。
- **依据**：Streamlit 1.63.0 源码 `streamlit/runtime/fragment.py` 明确支持 fragment 直接写入 `st.sidebar`，且「与 fragment 渲染到外部容器的 widget 交互，只重跑该 fragment，而非整个应用」；`st.rerun()` 在 1.63.0 的默认 scope 是 `"app"`，故跳转按钮行为不受影响。
- **验证（决定性，非肉眼）**：临时在 `main()` 注入整页 rerun 计数器（渲染成隐藏元素 `#dbg-runs`，**只有整页 rerun 才会 +1**），浏览器实测：

  | 操作 | data-n | 结论 |
  |---|---|---|
  | 页面加载 | 1 | — |
  | 点侧边栏角色进入聊天页 | 2 | 整页 rerun（切页，预期） |
  | **聊天页点「角色」展开** | **2** | **未触发整页 rerun ✅** |
  | 再点收起 | 2 | 未触发整页 rerun ✅ |
  | 点 😀 展开表情面板 | 2 | 未触发整页 rerun ✅ |
  | 点「返回主页」 | 3 | 整页 rerun（切页，预期） |

  ▼/▶ 文字切换正确，全程无 `StreamlitInvalidLayoutContextError`、无 Traceback。**验证后临时计数器已移除。**
- **坑**：`st.rerun(scope="fragment")` 若在「作为整页 rerun 的一部分运行」的 fragment 内被调用，会抛 `StreamlitInvalidLayoutContextError: scope="fragment" can only be specified from @st.fragment-decorated functions during fragment reruns`。本次实测正常路径（fragment rerun 中）不触发。

### 17. 「聊天大厅」主页重构：Hero 式角色展示 + 多角色 Carousel
- **需求**：主页定位是**角色选择大厅**（不是角色、也不是普通导航项）。原主页是「巨大白色矩形 + 圆形头像 + 名字 + 巨大粉色按钮」，像普通 SaaS/后台首页。要求改为「角色 + 场景 + 文字信息」的 Hero 式构图，角色立绘直接融入背景；**并且从现在就按多角色结构设计**（当前只有早濑优香，以后会加白子 / 星野等）。
- **实现**（只改 `frontend/streamlit_app.py`，聊天页与其 fragment/rerun 架构零改动）：
  - `render_home_page()` 重写为「标题 + Hero Carousel」；新增 `@st.fragment render_hall_carousel(characters)` 承载 Hero + 左右切换 + 指示点，以及 `_hall_step(delta)` 作为左右箭头的 `on_click` 回调（回调先于脚本执行，改完索引无需显式 rerun）。
  - **角色数据仍来自 `/api/characters`**（经 `load_characters_cache()`），**未写死任何角色名**；仅用 `st.session_state.hall_index` 记录当前下标，索引越界自动收敛回 0。
  - Hero 的三层视觉全部用 CSS `background-image` 叠加：① 左侧柔光渐变（保证文字可读）② 角色透明立绘（`assets/character/yuuka.jpeg`，实为 800×919 PNG RGBA）③ 场景背景（`assets/background/yuuka.jpg`）。**复用现有资源，未生成/未下载任何图片。**
  - 左右箭头 `‹ ›` + 底部位置指示点 `● ○ ○`：`count > 1` 才渲染箭头；只有一个角色时箭头隐藏、只显示 1 个点。第一版只做左右按钮，**未做拖拽滑动**（稳定性 > 动画），未引入任何前端框架。
  - 「开始聊天 →」沿用原有页面切换逻辑（`st.session_state.current_character_id = cid` + `st.rerun()`），切到哪个角色就进哪个角色的聊天页。
- **走过的坑**：
  - **绝对定位 `<img>` 塌成 0 高**：Streamlit 的元素容器自身是 `position: relative` 且**高度为 0**，绝对定位的立绘/背景层在里面 `boundingRect` 实测 `height = 0`（`naturalSize` 正常）。→ 彻底放弃绝对定位 `<img>`，改用 fragment 内动态注入 `<style>` 做 CSS 背景层叠加。
  - **标题颜色不生效**：Streamlit 自带 `h1` 规则特异性高于类选择器，`.hall-name` 显示为浅色。→ `color: #45405C !important;`。
  - **`fetch_characters() * 3` 无法用于多角色验证**：列表复制会产生**重复 `id`**，侧边栏 `key=f"nav_{id}"` 直接抛 `StreamlitDuplicateElementKey`。→ 改用「3 个不同 id 的克隆」做验证（真实数据 id 唯一，生产不受影响）。
- **验证（browser_use，Streamlit 每个浏览器标签页 = 独立 session，必须开新标签页才能拿到空 `characters_cache`）**：

  | 场景 | 检查项 | 期望 | 实测 |
  |---|---|---|---|
  | 单角色（真实数据） | `.hall-dot` 数 | 1 | 1 ✅ |
  | 单角色 | 箭头 `.st-key-hall_prev/next` 数 | 0（隐藏） | 0 ✅ |
  | 单角色 | `.hall-name` | 早濑优香 | 早濑优香 ✅ |
  | 多角色（临时 3 个不同 id） | 箭头数 | 各 1 | 各 1 ✅ |
  | 多角色 | `.hall-dot` 数 | 3 | 3 ✅ |
  | 多角色 | 点 `›` 后 activeIdx | 0→1→2 | 0→1→2 ✅ |
  | 多角色 | 点 `‹`×2 后 activeIdx | 0 | 0 ✅ |
  | 进入聊天页 | 点「开始聊天 →」后 `.st-key-hall_start` 数 | 0（已切页） | 0 ✅，聊天输入框存在 ✅ |

  **验证后临时多角色代码已还原**（`load_characters_cache()` 恢复为 `st.session_state.characters_cache = fetch_characters()`）。
- **未决 / 待确认**：Hero 里的欢迎语目前是**通用兜底文案** `「你好呀，我是{角色名}～今天想和我聊点什么？」`（不对任何具体角色写死）。若要实现角色专属台词（如「老师，今天也要认真工作哦。」），需在**后端角色数据中新增 `greeting` 字段**——因本次约定不得直接改其他文件，待用户确认后再做。
- **视觉精修（同日，只做减法，不改数据结构 / 不碰聊天页 / 不碰后端）**：
  - 删除「当前角色」小标签（`.hall-eyebrow` 的 HTML + CSS 一并移除），让角色名直接成为标题。
  - 角色名 46px → **38px**，不再与右侧立绘抢视觉中心。（**坑**：Streamlit 自带 `h1` 规则 `2.75rem = 44px` 特异性高于类选择器，`font-size` 同样必须加 `!important` 才生效——实测未加时为 44px。）
  - 名字下方点缀由「54×4px 实心粉色块」改为 **118×3px + `mask-image` 向右渐隐**的柔和一笔，去掉模板装饰感。
  - 左右切换按钮从"底部一行"改为**放在 Hero 卡片外侧的左右两边**（`st.columns([1, 20, 1], vertical_alignment="center")`，无绝对定位，稳定优先），34px 小圆按钮（先做过贴在卡片内侧的 44px 版本，按用户要求改为卡外 + 更小）；**只有一个角色时不再隐藏而是置灰**（`disabled=True`，白底 0.9 + 淡色箭头），保留"这里可以切换"的视觉提示，且不虚构任何角色。
  - 底部轮播指示点**保留**；左侧角色列表**未改动**。
  - 字形颜色/字号同时落到 `button` 与其内部 `p` 上（Streamlit 自带的 `p` 规则会覆盖 `button` 上的声明）。
  - **验证**（Playwright + 系统 Chrome，1440×900）：`.hall-eyebrow` 数 = 0、`.hall-name` = 早濑优香 / computed `font-size` = **38px**、箭头各 1 个且 `disabled=true`、指示点 = 1、`.hall-accent` computed `width` = 118px 且 `mask-image` 为 `linear-gradient(...)`；几何上左箭头 x=324→358、右箭头 x=1377→1411，均在 Hero 卡片（x=379→1361）**外侧**，且箭头中心 y=435 与卡片中心 y=435 完全一致（垂直居中）。

---

## 2026-10-03

### 18. 主页 Carousel 切换滑动动画（纯 CSS，零 JS / 零框架）
- **需求**：点 ‹ / › 切角色时，Hero 卡片有滑动过渡，而不是瞬间替换。
- **难点**：Streamlit fragment rerun 是**原地换内容**（Hero 容器 DOM 节点被复用），而 CSS 动画只在「宿主元素重新创建」或「`animation-name` 变化」时才重放——把动画名写死在静态 CSS 里只会播一次。
- **解法**：
  - `_hall_step` 回调除改 `hall_index` 外，再记 `hall_dir`（±1 方向）并自增 `hall_anim_seq`。
  - fragment 每次渲染动态注入 `<style>`：`@keyframes hall-in-{seq}` + `.st-key-hall_hero { animation: hall-in-{seq} 0.45s cubic-bezier(0.22, 0.61, 0.36, 1) both; }`。**动画名内嵌自增序号 → 每次切换名字必变 → 浏览器必然重放**。
  - 方向感知：→ 切下一个从 `translateX(64px)` 滑入，← 切上一个从 `-64px`；起点 `opacity: 0.15`（刻意不做全透明淡入，避免"淡"盖过"滑"）。
  - 首次渲染 `seq=0` 不动画；`prefers-reduced-motion: reduce` 时禁用（无障碍）；`both` 填充模式保证起始帧不被闪现。
- **验证**（Playwright + Chrome，真实双角色 mika / yuuka）：点击后中间帧实测 hero computed `transform: matrix(1,0,0,1,64,0)`、`opacity: 0.15`、活动动画实例 `hall-in-1@450ms`；落定后 `opacity: 1`、角色名正确轮换、2 个指示点、控制台零错误；侧边栏 / 箭头 / 指示点等周围元素全程全透明度不受影响。
- **测试脚本踩坑**：`document.getAnimations()` 混有 CSS transition 实例（没有 `.animationName` 属性，谓词必须判空否则 TypeError），且会持续返回 `fill: both` 的**已结束**动画——判断"新动画开播"不能只看名字前缀。

### 19. 侧边栏重设计：改为「AI 角色陪伴应用」风格的角色栏
- **需求**：旧侧边栏是「巨大白色按钮堆」（角色分组大按钮 + 群聊/语音大白条 + 设置/返回大白按钮），像后台管理系统。要求改造成角色陪伴应用风格：视觉层级 **角色 > 功能菜单 > 设置**，角色列表带头像/名字/在线状态，选中态轻盈（半透明主题色 + 细左侧指示条），群聊/语音降为次级，设置/返回主页压底轻量化。**只改 `frontend/streamlit_app.py` 的视觉层，禁改后端/API/CharacterService/聊天逻辑/fragment/切换逻辑。**
- **实现**：
  - **Python 侧（纯呈现层，交互逻辑零改动）**：`render_sidebar()` 重写为「品牌区(sb-brand) → 角色(可折叠小标题) → 角色列表 → ＋添加角色(纯视觉) → 更多功能(群聊/语音弱化) → sb-spacer 弹性空间 → 底部 设置/返回主页」。`@st.fragment` 装饰器、`st.rerun(scope="fragment")`、跳转按钮的 `st.rerun()`、`nav_{id}` 按键全部原样保留。新增 4 个辅助函数：`_hex_to_rgb`（主题色→rgba）、`_sidebar_char_html`（选中角色行的 HTML：头像+名字+在线+主题色高亮）、`_sidebar_char_css`（未选中角色按钮的按角色 CSS：头像 background-image + ::after 在线行）、`_render_sidebar_characters`（遍历 `/api/characters` 数据渲染，每角色一份样式，不写死角色名，加角色自动扩展）。
  - **CSS 侧**：品牌区轻盈（18px 粗体标题 + 11px 弱副标题）；「角色」小标题 12px/透明；选中行 `.sb-char-active`＝主题色 12% 透明背景 + 3px 左指示条 + 36px 圆头像 + 14px 加粗名字 + 绿点在线；未选中按钮透明、hover 轻微白底 + 主题色文字（**hover 只写 `background-color`，写 `background` 简写会清掉按钮上的头像 background-image**）；群聊/语音/添加角色 12px 弱化灰字；底部导航 34px 半透明小按钮。无头像时用主题色圆底 + 名字首字兜底（不创建空图片文件）。
- **走过的坑**：
  - **CSS 特异性平局**：角色按钮规则注入在侧边栏（DOM 靠前），主区注入的通用按钮兜底规则同特异性 (0,1,1)——平局按文档顺序后者胜，垂直居中/字号会被兜底覆盖。→ 所有侧栏专属规则统一加 `[data-testid="stSidebar"]` 前缀提高到 (0,2,1)。
  - **`.sb-spacer` 弹性空间不生效（两层原因）**：
    1. `st.markdown` 输出外面有**四层包裹盒**（stElementContainer > stMarkdown > 排版div > stMarkdownContainer），spacer 的 `flex-grow` 在内容自适应高度的包裹盒里无效。→ 用 `display: contents` 把四层全部穿透，spacer 成为 `stVerticalBlock` 的直接 flex 子项。
    2. **嵌套 `:has()` 不可用**：写成 `div:has(> X:has(.sb-spacer))` 时 Chrome 不支持，且 CSS 选择器列表中**一条非法会令整条规则被丢弃**（连已生效的穿透层一起失效回退）。→ 改为单层 `:has()` 的等价写法 `[data-testid="stMarkdown"] > div:has([data-testid="stMarkdownContainer"] .sb-spacer)`。
    3. `stSidebarUserContent` 默认 `padding-bottom: 6rem`(96px) 的滚动留白把底部导航顶离底边。→ 压到 16px；同时高度链改 flex 全链（stSidebarContent 改 flex 列、userContent `flex:1 + min-height:0`），避免 `height:100%` 让内容区溢出 header。
- **验证**（Playwright + 系统 Chrome，1440×900，52 项断言全过）：双角色头像 URL 均注入且 HTTP 200、`::after` 在线行生效、按钮透明非白卡、52px 紧凑高度、内容垂直居中；点优香 → `.sb-char-active` 出现（名字/头像/在线/主题色 #FF6B9D、rgba 12% 背景、左指示条），点未花切换正确（#7EC8E3）；设置页/返回主页可达；聊天页 character-info/立绘/输入框正常；**「角色」收起/展开两次后主页 Hero DOM 节点身份不变（`isConnected` 同一节点）＝ fragment 防闪烁方案未受影响**；每角色一份 CSS 注入（数据驱动可扩展）；控制台零错误；底部导航距侧栏底边 22px（弹性空间 + 16px padding 生效）。

### 20. 角色专属开场白（greeting 字段全链路）
- **需求**：把两个角色通用的兜底开场白「你好呀，我是{角色名}～今天想和我聊点什么？」换成角色专属台词（优香：老师，您来啦…；未花：诶～老师来啦…♪）。
- **实现（数据驱动，不在前端写死任何角色）**：
  - `characters/{yuuka,mika}/character.json` 新增 `greeting` 字段（存纯文本，不带「」）；
  - `backend/services/character_service.py`：`CharacterConfig.__init__` 读入 `greeting`（默认空串），`to_public_dict()` 透传给前端（第 17 条遗留的「未决」项落地）；
  - `frontend/streamlit_app.py` 两处接入，均为「优先 greeting、缺省回落通用文案」：
    - 主页 Hero：有 greeting 时包上「」显示；
    - 聊天页空对话欢迎框（welcome-box）：有 greeting 时整句替换「你好呀，我是XX～ / 今天想和我聊点什么？」两行。查找角色数据用 `load_characters_cache()`（session 缓存，无额外请求），未改 fragment 签名与结构。
- **注意**：CharacterService 是启动时单例——改 character.json 后必须重启后端才生效（与 prompt.txt 同理）。本次后端已由助手重启。
- **验证**（requests + Playwright + Chrome）：`/api/characters` 两个角色均返回各自 greeting；主页 Hero 未花→优香切换后各自台词正确显示；聊天页空对话 welcome-box 显示各自台词；截图 greet-{mika,yuuka}-chat.png。

---

## 2026-10-03

### 21. 新增：聊天语音功能（中文聊天 + 日语 GPT-SoVITS 语音）
- **需求**：文字聊天保持中文，语音单独链路——中文回复 → 翻译成日语 → 现有 GPT-SoVITS 合成角色日语语音；聊天页右上角 🔊 作为全局语音开关；TTS 不得阻塞文字显示、不得破坏 st.fragment 防闪烁结构。
- **GPT-SoVITS 接入调研（不改本体、不重训）**：
  - 主仓库从 `F:\AI_3D_Mate` 整体迁入 `F:\YuukaChat\GPT-SoVITS-v2pro-20250604`（同盘瞬间移动，15.7GB；config.py/weight.json 均为相对路径，无旧路径依赖）；
  - 实际使用的是 **api.py (v1)**：`GET /?text=&text_language=&refer_wav_path=&prompt_text=&prompt_language=` 返回 WAV 流，`POST /set_model` 切权重（api_v2.py 的 /tts 未用）；
  - 日语优香权重 `YouXiang-e5.ckpt + YouXiang_e8_s192.pth`（weight.json 默认即此组合，YuukaVoice 旧项目验证过）；参考音频 `Yuuka_Season_Birthday_Player.wav`（日语）复制为 `characters/yuuka/reference.wav`；
  - 关键澄清：旧代码里 `text_language="zh"` 只是当年的中文 TTS 测试，模型本身支持 `ja`（api.py dict_language 有 ja/all_ja 映射），本次端到端实测 `text_language=ja` 合成正常。
- **后端（只增不改，/api/chat 与 /ws/chat 一行未动）**：
  - 新增 `backend/services/tts_service.py`：① Ollama 中→日翻译（独立一次性调用，不带聊天历史，temperature 0.3，复用角色模型）；② GPT-SoVITS 合成（参考音频等参数**逐请求传入**，不依赖 API 端 session 状态，天然多角色兼容）；③ 权重懒加载（进程内记 `_loaded_weights`，只在变更时调 /set_model）；④ 文件缓存 `backend/cache/tts/`（key=sha1(角色id|中文文本)，6 小时 / 60 个文件自动清理，不无限积累）；
  - `main.py` 新增 `GET /api/tts-audio`（中文文本进、WAV 出，内部完成翻译+合成；Cache-Control 24h）与 `GET /api/tts/status`（前端探测 GPT-SoVITS 是否在线）；
  - `character_service.py`：`CharacterConfig` 读取 character.json 可选 `tts` 块；`to_public_dict()` 新增 `has_tts`（未配置 tts 的角色前端不渲染任何音频，多角色零耦合）；
  - `characters/yuuka/character.json` 新增 `tts` 块：gpt_model/sovits_model/refer_wav_path/prompt_text/prompt_language/text_language 全部数据驱动——以后给未花加语音只需放参考音频 + 加配置块，聊天逻辑零改动。
- **前端（fragment 流程零改动，音频纯渲染层注入）**：
  - 🔊 从静态占位 span 改为真实开关按钮，位于聊天 fragment 顶部右侧（`[class*="st-key-voice_toggle_"]` CSS 去边框）；`session_state.voice_enabled` 默认开、刷新重置；
  - **开关防闪烁（用户反馈修复）**：最初把按钮放在 fragment 外的角色信息行，点击触发整页 rerun，立绘/背景闪烁回归；移入 `render_chat_fragment` 顶部后点击只 fragment 局部 rerun。状态翻转必须走 `on_click` 回调（渲染前执行）——若用 `if st.button(): 翻转` 模式，按钮在翻转前已用旧图标渲染完，图标会滞后到下一次 rerun（旧实现正是靠补 `st.rerun()` 强制第二次整页重绘掩盖此问题，双重闪烁根源）。修复后回归测试通过：开关点击后 `.character-stage` 节点身份不变（无整页重绘）、图标同次 rerun 即更新、音频正确显隐、重开不重播、控制台零错误；
  - **非阻塞设计**：`render_chat_fragment` 消息循环里给 assistant 气泡追加 `<audio class="bubble-audio" src="后端/api/tts-audio?...">`，音频由浏览器后台 fetch，fragment run 内**零网络等待**——文字显示速度与加语音前完全一致，语音生成期间输入框立即可用；
  - 播放控制：仅最新一条 AI 回复 `autoplay`（`played_audio_keys` 集合防 fragment 重绘/整页 rerun 重复播放），旧消息 `preload="none"` 手动点播；语音关闭时不渲染 `<audio>` → URL 不被请求 → 零翻译零合成零计算；
  - TTS 在线状态在整页渲染时检查（`tts_up`，60 秒缓存），fragment 重绘不发起网络请求。
- **实测**：稳态合成 4.4s（翻译 ~2s + TTS ~2.4s，浏览器后台进行不占交互）；缓存命中 0.01s；Playwright 全链路 8 项通过——未花页无音频（has_tts 隔离）、优香回复后音频元素出现且最新条 autoplay、浏览器实际请求 /api/tts-audio、**fragment 隔离回归（emoji 交互后舞台节点身份不变）**、开关切换行为正确（关→无音频+🔇，重开→音频恢复且不重播）、控制台零错误。
- **教训**：Playwright `button:has-text(...)` 会匹配到 Streamlit 在 DOM 里保留的隐藏按钮副本（`visible=False`、无 bounding box），断言须用 `count() >= 1` + 可见性判断，不能写 `count() == 1`；浏览器渲染需要读系统字体（C:\WINDOWS\FONTS），Playwright 测试须在沙箱外运行。

### 22. 新增：一键启动脚本 start_all.bat
- 双击即可拉起全部服务：Ollama（11434）→ 后端（8000）→ GPT-SoVITS（9880）→ 前端（8501），各自独立 `cmd /k` 窗口便于看日志，关窗即停对应服务；
- 端口探测防重复启动：已在运行的服务自动跳过；Ollama 未运行时尝试 `ollama serve`，未安装仅提示不阻塞；
- 细节：UTF-8 无 BOM + CRLF 行尾 + `chcp 65001`（中文提示防乱码）；已实测跳过逻辑与输出正常（四个服务在线时全部正确跳过）。

### 23. 修复：隐藏输入框 "Press Enter to apply" 提示小字
- 现象：Streamlit 1.63 的 st.text_input 改为"失焦/回车才提交"，输入或删除时框内右侧出现灰色英文小字提示；
- 该版本 text_input 无 accept-mode 参数可关，用 CSS 隐藏：`[data-testid="stTextInput"] [data-testid="InputInstructions"] { display:none !important; }`（选择器经 Playwright 实测 DOM 确认）；
- 纯视觉隐藏，提交行为不变：直接点发送时输入框自动失焦、值先提交再执行 on_click，不丢字（此前 Playwright 发送流程测试已覆盖）。
### 24. 语音系统复测：全链路通过 + start_all.bat「没有语音」排查
- **背景**：用户反馈「语音系统单独实测通过，但用 start_all.bat 打开时没有语音」，并提供 GPT-SoVITS 9880 启动日志（`WARNING: 未指定SoVITS模型路径 fallback...` / `未指定GPT模型路径` / `未指定默认参考音频`，fallback 到 v1 预训练模型）。
- **排查（全部通过）**：
  - 文件核对：`characters/yuuka/reference.wav`（773KB）、`GPT_weights_v2/YouXiang-e5.ckpt`（155MB）、`SoVITS_weights_v2/YouXiang_e8_s192.pth`（85MB）全部存在；
  - 服务核对：9880 在线（GET / 返 400 为缺参正常）、`/api/tts/status` 返回 `{"tts_available":true}`；
  - 直接 `curl /api/tts-audio?character_id=yuuka&text=...`：**返回正常 WAV（HTTP 200）**——翻译+合成链路通。
- **结论：那条 fallback WARNING 不是问题**。设计就是启动时不带模型（api.py 无 `-s/-g` 参数），首次合成时 `tts_service._ensure_weights` 自动 POST `/set_model` 加载优香 v2 自定义权重（`_loaded_weights` 进程内防重复加载），实测合成音频正常。
- **前端端到端实测（Playwright 有头 + `--autoplay-policy=no-user-gesture-required`，audio 状态时间线）**：4s `rs=0 net=2`（合成中）→ **14s `rs=4`、时长 10.7s、自动播放成功（paused=false，currentTime 递增）** → 26s 播完 → **36s 又自动播了一遍**。
- **「start_all.bat 打开时没有语音」最可能原因（按概率）**：
  1. **GPT-SoVITS 9880 首次权重加载约 1 分钟**（bat 注释已写）——刚双击启动就发消息，合成失败/超时；等 1 分钟后再发即有语音；
  2. **浏览器自动播放策略**——刷新后旧回复的 autoplay 可能被 Chrome/Edge 拦截（地址栏右侧「声音已阻止」图标）；
  3. 前端 🔊 开关当前实测为 `stButton`（🔊 图标按钮，非 checkbox toggle）。
- **发现小瑕疵（待用户决定是否修）**：26s 播完后 36s **重复自动播放了一遍**——`played_audio_keys` 防重播未完全防住 fragment 重绘场景。
### 25. 修复：「start_all.bat 刚启动后发消息无语音、必须刷新才恢复」（tts_up 被 60 秒缓存锁死）
- **现象（用户多轮实测）**：进程刚起、立刻进优香聊天页发消息 → 文字正常回复但**无语音、气泡下无播放器**，且 GPT-SoVITS 9880 终端除健康检查 `GET / 400` 外**一条请求都没有**（等 10 分钟也无变化）；**刷新页面后再发就有语音**（首次合成慢、第二次快）。用户澄清：about:blank 在所有网址都有的极细白边与本问题无关（那是浏览器级现象，两者并存但不是一回事）。
- **根因（代码级定位）**：`tts_up`（TTS 在线探测）只在 `render_chat_page`（**fragment 外**）整页渲染时检查、且有 **60 秒缓存**；而 audio 渲染条件（fragment 内）= `voice_enabled AND tts_up AND has_tts`。因果链：刚启动时 9880 未就绪 → 首次整页渲染探测失败 → `tts_up=False` 缓存 60 秒 → **发消息只触发 fragment rerun、根本不经过这段检查** → 即使缓存过期也永远不重查 → audio 永不渲染、浏览器不请求音频、9880 收不到请求（终端静止）→ **刷新 = full-app rerun = 重新探测 = 9880 已就绪 = 有语音**。完全解释全部现象。
- **解决（`frontend/streamlit_app.py`）**：探测块从 `render_chat_page` **移入 `render_chat_fragment`**（fragment 内），缓存 **60 秒 → 5 秒**。效果：进聊天页立刻发消息即探测，9880 就绪就有语音；即使 9880 恰好未起，几秒后再发消息自动恢复，**无需刷新整页**。本地探测 ~3ms 零负担，短缓存同时避免 9880 异常时每次发消息都等 3 秒超时。
- **改动边界**：不碰 fragment 结构 / rerun 逻辑 / backend / 背景 / 立绘 / character-info。
- **验证**：语法通过；待用户实测「进程重开 → 立刻进优香发消息 → 直接有语音（不刷新）」。
### 26. 新增：现实时间感知（后端每次请求动态注入 system prompt）
- **需求**：AI 每次生成回复时知道当前电脑真实日期/星期/时间，但不每句都提时间、不加任何工具调用机制（time tool / function calling / MCP / 前端时间组件都不要）、不写入 history、不改前端与人设。
- **实现（`backend/services/llm_service.py`，唯一改动文件）**：
  - 新增 `@staticmethod _time_context()`：`datetime.now().astimezone()` 动态生成（Windows 本机时间与时区），Python 直接算星期（`"一二三四五六日"[weekday()]` 映射）与时间段（05-8 清晨 / 9-11 上午 / 12-13 中午 / 14-17 下午 / 18-21 晚上 / 22-4 深夜），减少小模型自行推算的负担；输出【当前现实时间】（日期/时间/星期/时间段）+【时间使用规则】（不机械提时间、不主动汇报、不强改话题、无关时自然聊天）；
  - `chat_stream` 内 `effective_prompt = char_cfg["prompt"] + "\n\n" + self._time_context()`，作为 system prompt 传给 Ollama；
  - **时间不写 history**：history 只 `extend` 前端传入的 user/assistant 消息，时间只进 system prompt，每次请求重新生成最新时间（历史时间会过期、且会积累无意义 token）；
  - `/api/chat` 与 `/ws/chat` 两个端点自动全覆盖（都走 `chat_stream`）。
- **改动边界**：未改 character prompt.txt / 前端 UI / fragment / emoji / TTS / 角色切换 / 背景 / character_service / Ollama 模型配置 / API 路由结构。
- **测试（6 项全过）**：
  1. "你好呀" → "晚上好，老师。今天过得怎么样？"（自然参考时间，未机械汇报"现在是23:08"）✅
  2. "现在几点了？" → "已经是深夜了，老师。都快十一点了呢。"（正确报出真实时间）✅
  3. "优香，今天好累。"（深夜 23 点）→ "辛苦了，老师。要不要稍微休息一下？"（自然利用时间关怀）✅
  4. "帮我算一下 123 + 456" → 正常计算 579，未强行提时间 ✅
  5. 时间动态性：`_time_context()` 每次 `chat_stream` 调用都执行 `datetime.now()`（分钟粒度；测试 2 回复时 23:11 → 复测 23:23，跨请求时间已更新）✅
  6. history 干净：时间只进 system prompt，history 仅含 user/assistant 消息 ✅
- **坑**：start_all.bat 后端启动命令（第 26 行 `python -m uvicorn main:app --host 127.0.0.1 --port 8000`）**不带 `--reload`**——改后端代码必须重启后端进程才生效。本次测试曾出现"下午好/报不出时间"即未重启导致的旧代码，重启后全部正常。
### 27. 新增：二次元风格小型日历（character-info ♡ 左侧 📅 入口，纯前端交互零 rerun）
- **需求**：在角色信息栏 ♡ 按钮左侧加 📅 日历入口，点击展开小型浮动日历面板（二次元/粉紫/半透明白/毛玻璃/圆角/樱花装饰）；Python 动态生成系统真实日期，月份切换纯前端；不破坏 fragment 防闪烁架构、不抢视觉重点。
- **关键技术结论（Streamlit 内执行 JS 的唯一可行路径）**：
  1. **`st.markdown(unsafe_allow_html=True)` 的 `<img onerror="...">` 不可行**——Streamlit 前端把 HTML 逐属性解析成 React 元素，内联事件 handler 被当作 React prop（onError）收到字符串 → 抛 `Minified React error #231`；
  2. **`st.html()` 也不执行 script/onerror**（实测 `window.__t=0, __t2=0`，全被拦截）；
  3. **唯一可行：`streamlit.components.v1.html`（iframe）**——iframe 内 JS 能执行，且 **srcdoc 与父页同源**，iframe 内 JS 可通过 `window.parent.document` 操作外页 DOM（面板开合/月份切换/网格渲染全在 iframe 内 JS 完成）。
- **实现（`frontend/streamlit_app.py`）**：
  - `render_chat_page` 内 Python 生成今天数据（`datetime.now().astimezone()`，中文星期/时间段），拼进面板底部 cal-foot（切月份不重算，今天信息始终真实）；
  - `cal_js`（iframe 内 script）：操作外页 `#cal-panel` 开合、`#cal-prev/#cal-next` 月份切换（年份进退位）、`#cal-grid` innerHTML 渲染（前置/尾部置灰 + 周日粉/周六蓝 + 今天粉色高亮，仅真实当前日期高亮）；同时用 `window.frameElement.closest` 找到自身 stElementContainer，读外页 `#cal-slot`（♡ 左侧 36px 占位锚点）位置后 `setProperty("position","fixed","important")` 精确定位并显示；
  - 重定位时机：双帧 rAF + `setTimeout(300/1000)` 补偿（字体加载后布局漂移）+ 父窗口 resize 监听；
  - CSS：`.cal-slot` 占位锚点；`[data-testid="stElementContainer"]:has(iframe[srcdoc*="cal-btn"])` 默认 `visibility:hidden + height:0 !important`（不占文档流，JS 定位后显示——避免首帧把立绘下推的跳动）；面板半透明白毛玻璃 rgba(255,255,255,0.88) + blur(12px) + 粉边框 + 樱花装饰（`.cal-today::after` ✿）。
- **坑（诊断 4 轮定位）**：首版 iframe script **静默不执行**（onclick=null、cal-title 空、console 无 error）——根因是 cal_js 结尾残留旧方案 IIFE 自调用的 `')()'`，与 cal_iframe 拼接的 `'}());` 重复 → `(function(){...render();)()}())` 语法错误 `Unexpected token ')'`，**语法错误的 script 整体不执行且只在 pageerror 事件（console.error 捕不到）**。定位方法：在 iframe 内 `(0,eval)(code)` 重新执行捕获异常。教训：srcdoc script 失败先查语法错误、监听 pageerror。
- **修复（2026-10-07 用户截图反馈「图标歪了」）**：📅 显示在 ♡ **下方一行**——根因是 `.cal-slot` 空占位（inline-block 高度为 0），place() 把 iframe **顶部**对齐 slot 顶部，按钮（36px 高）整体比 ♡ 中心低 18px；此前 playwright 对齐检查 dy=0 只对了 slot 顶部、未对比 ♡ 中心，故未抓到（教训：视觉对齐检查须对比**双方视觉中心**，不能只对锚点顶部）。修法：place() 改**中心对齐**（`left = r.left+r.width/2-18; top = r.top+r.height/2-18`）+ `.cal-slot` 给 `height:24px`；同时健壮化：cal-prev/cal-next/点外关闭从独立 onclick 绑定改为**外层 document 事件委托**（每次实时 getElementById，外层 DOM 重建而 iframe 未重载时仍工作）；测试脚本对齐判据同步改为「按钮中心 vs ♡ 中心」并给点击加重试。
- **改动边界**：不碰 fragment 结构/rerun 逻辑/backend/背景/立绘/character-info 结构/emoji/TTS；日历交互全部纯前端 JS，零 Streamlit rerun。
- **验证（playwright 有头，功能 11/11 + rerun 存活 4/4 全过 + VLM 视觉确认）**：
  - 功能：iframe 存在、容器 fixed 定位、按钮中心与 ♡ 中心垂直居中（dy=0.0）且在 ♡ 左侧同行（dx=37.5 为布局预期值）、点击打开、标题「🌸 2026年10月」、10 月网格 35 格（4 置灰 + 31 天）、今天 7 粉色高亮、‹›切 11/9 月正常、切月后无今天高亮、回到 10 月高亮恢复、点外关闭；
  - rerun 存活：fragment rerun（空发送）后点外关闭生效 + 定位保持 + 再次点击仍正常打开；full-app rerun（侧栏交互）后 iframe 重建、JS 重新执行、日历正常工作；
  - VLM 视觉：标题/箭头/星期行/网格/今天高亮/底部今天信息完整，毛玻璃 + 圆角 + 粉色光晕，无布局错乱无文字溢出；修复后 character-info 区域截图确认 📅 与 ♡ 同行、垂直居中、间距合理、无偏移。
- **保留回归脚本**：`dbg_calendar.py`（功能 11 项）、`dbg_calendar_rerun.py`（rerun 存活 4 项）。
### 28. 修复：语音开关回到角色信息行（🔊 被 fragment 顶部 columns 挤到最右、很不明显）
- **现象（用户截图反馈）**：🔊 语音开关在聊天 fragment 顶部 `st.columns([0.9, 0.1])` 第二列（最右 10% 宽度），位置偏、很不明显；原本人设期望是角色信息行「… ♡ 🔊」。
- **方案（保持 fragment 防闪烁架构不变）**：fragment 内真实 `st.button`（`voice_toggle_`，承载 `on_click=_toggle_voice` 与 fragment rerun）**保留但 CSS 隐藏**（`[class*="st-key-voice_toggle_"] { display:none !important; }`）；character-info 的 ci-actions 最右（♡ 右侧）加 `voice-slot` 占位 + 🔊 iframe 按钮（日历同款 components.html 机制）。
- **实现**：iframe 内 JS ① `place()` 定位到 voice-slot 中心（同日历：fixed + 双帧 rAF + setTimeout 300/1000 + resize 监听）；② 点击 `realBtn.click()` **模拟点击隐藏的真实按钮**（DOM 事件不依赖可见性，Streamlit on_click 正常触发 fragment rerun）；③ `sync()` 每 500ms 轮询真实按钮 `textContent`（含 🔊/🔇）同步 iframe 图标（fragment rerun 后图标自动跟上）。
- **改动边界**：不碰 fragment 结构/rerun 逻辑/backend/背景/立绘/日历；`_toggle_voice` 与 st.button 完全不动，只 CSS 隐藏 + 视觉层新按钮。
- **验证（playwright 有头 9/9 全过 + VLM 视觉确认）**：iframe 存在、容器 fixed 定位、🔊 在 ♡ 右侧同行垂直居中（dy=0）、真实按钮 display:none、初始 🔊、点击翻转 🔇（轮询同步）、点击后 character-info 位置不变（fragment rerun 零重绘）、再点恢复 🔊、日历回归正常；VLM 确认三图标同行居中、🔊 清晰可见、聊天区顶部无残留按钮、无布局错乱。
### 29. 新增：圣园未花（mika）语音系统（GPT-SoVITS 微调权重接入，像优香一样）
- **需求**：用户下载了未花语音文件（F:\未花\v4\未花\：未花-e10.ckpt 148MB GPT 权重、未花_e10_s140_l32.pth 72MB SoVITS 权重、reference_audios/日语/emotions/【默认】ふんんー？今度は貴方たち？.wav 参考音频），像优香一样加入项目。
- **实现（零代码改动，纯配置 + 文件接入）**：
  - 权重复制进项目（与优香统一结构）：`GPT-SoVITS-v2pro-20250604/GPT_weights_v2/Mika-e10.ckpt`、`SoVITS_weights_v2/Mika_e10_s140.pth`（ASCII 命名稳妥）；参考音频 → `characters/mika/reference.wav`；
  - `characters/mika/character.json` 加 tts 块（refer_wav_path/prompt_text「ふんんー？今度は貴方たち？」取自参考音频文件名/prompt_language=ja/text_language=ja）；
  - 后端 tts_service 角色无关（逐请求传参 + /set_model 权重切换），**无需任何代码改动**；`has_tts=bool(refer_wav_path)` 自动生效；CharacterService 启动时加载 → **重启后端生效**。
- **验证（全链路全过）**：
  - 后端合成：短文本「老师，今天好开心呀。」→ 200、2.5s WAV（48000Hz）✅；长文本（未花回复 ~100 字）→ 200、18.2s、16.4s WAV ✅；
  - 权重自动切换：未花 set_model 合成后 → 优香请求自动回切优香权重 → 2.0s WAV（32000Hz 优香音色）✅ 多角色共存正常；
  - 前端端到端（playwright 有头 6/6）：侧栏「圣园未花」进聊天页、🔊 iframe 按钮 🔊、发消息 → audio 播放器渲染（约 16s 合成后 readyState≥2）、自动播放 paused=false（7.64s 音频）、currentTime 递增。
- **排查小坑**：① bash 对中文+日文混合路径处理不稳（du/ls 报错），复制一律用 python shutil + os.listdir；② 文件名实际为 `未花_e10_s140_l32.pth`（下划线），ls 显示曾误读为连字符；③ 首次端到端 audio 未 ready 是该轮回复合成较慢（18s+），非缺陷——等待给足即可。
### 30. 修复：问时间偶说不准（历史回复里的旧时间被小模型混淆）
- **现象（2026-10-08 23:53 用户截图反馈）**：问时间时系统明明是 23:53，AI 回复的时间不准。当前直接实测（问「现在几点了？」→「23:55了呢～」）注入与回复均准确——问题出在**同一会话的历史里 AI 回复带过旧时间**（此前 23:11/23:23 问过时间，那些回复进了 history），小模型混淆历史旧时间与 system prompt 当前时间。
- **修复（`backend/services/llm_service.py` 的 `_time_context` 时间规则，唯一改动）**：
  - 加「历史对话里任何人提到的任何时间都可能已过期，一律忽略；当前时间只以本提示的【当前现实时间】为准」；
  - 加「用户问时间时，直接引用【当前现实时间】里的时间数字，不要自行推算或四舍五入」。
- **改动边界**：不动 chat_stream 结构 / history 机制 / 前端 / 时间生成逻辑（datetime.now() 每次准确，问题只在模型表述规则）。
- **验证**：重启后端（start_all.bat 后端不带 --reload，改后端必须重启），跨 75 秒两次提问模拟混淆场景：第 1 次（系统 23:57:22）→「23:57 呢～」✅；第 2 次带「23:57」旧回复的历史（系统 23:58:44）→「23:58 呀！」✅ 用最新时间、未混淆历史。

### 31. 传 GitHub 前准备：清理残留 + 全仓相对路径化 + .gitignore（2026-10-09）
- **清理**：删 5 个诊断截图（_diag_white.png、dbg_cal_*.png×3、dbg_mika_voice.png）、backend.log、后端启动.txt、frontend 实验残留（component/、index.html、node_modules/、.npm-cache/——旧 declare_component 方案构建产物，grep 确认无代码引用）、cache/tts 运行时语音缓存。保留 dbg_calendar.py / dbg_calendar_rerun.py 回归脚本。
- **相对路径化（仓库 clone 到任何机器/盘符可直接跑）**：
  - start_all.bat 4 处写死 F:\YuukaChat → %~dp0（自带尾随反斜杠，拼接 cd /d %~dp0backend 等）；
  - 两个 character.json 的 tts 路径由绝对路径改为**项目根相对路径**（如 GPT-SoVITS-v2pro-20250604/GPT_weights_v2/YouXiang-e5.ckpt、characters/yuuka/reference.wav）；
  - backend/services/tts_service.py 新增 PROJECT_ROOT + _resolve_path()：**已是绝对路径原样返回（向后兼容），相对路径按项目根解析**——GPT-SoVITS 是独立进程（工作目录在它自己那边），收到相对路径会解析错，必须在 _ensure_weights（gpt/sovits 权重）与 synthesize（refer_wav_path）传参前转为绝对路径。
- **新增 .gitignore**：GPT-SoVITS-v2pro-20250604/（数 GB：runtime Python + 预训练模型 + 微调权重，超 GitHub 100MB 单文件限制，README 写下载说明）、cache/、__pycache__/、*.pyc、.ruff_cache/、.codeartsdoer/、.merkle-snapshot.json、pyrightconfig.json、*.log、dbg_*.png、.streamlit/secrets.toml、系统杂项。注意 dbg_*.py（回归脚本）**不在忽略列表**，随仓库上传。
- **验证（重启后端，两角色合成全过）**：优香 → 200、1.8s WAV（32000Hz）；未花（切角色 set_model）→ 200、2.4s WAV（48000Hz）——相对路径被正确解析，语音链路正常。
- **TTS 依赖结论（回答用户提问）**：**文件依赖全部在项目内**（GPT-SoVITS 框架 + 自带 runtime + 预训练模型 + 微调权重 + 参考音频）；运行时外部依赖仅 Ollama 服务 + qwen2.5:7b 模型（聊天推理与 TTS 的日语翻译）与系统 Python + pip 包（后端/前端；GPT-SoVITS 用自带 runtime 不依赖系统 Python）。
- **坑（服务重启链）**：验证时 9880/11434 均已掉线（GPT-SoVITS 与 Ollama 进程停了）——重启时 bash nohup 后台进程会随命令结束被杀，cmd start 被安全策略禁止，须用 powershell Start-Process 完整路径 -ArgumentList serve -WindowStyle Hidden -PassThru 启动独立进程；GPT-SoVITS 就绪约 1 分钟（轮询 9880 得 400 即健康）、Ollama 就绪约 5-10 秒；F:\Ollama\ollama.exe 不在系统 PATH（start_all.bat 的 where ollama 探测会 miss，但 Ollama 桌面版通常已自启）。
### 32. 新增：双人群聊系统 MVP（老师 + 优香 + 未花）（2026-10-10）
- **需求**：用户发布群聊 MVP 规格——固定顺序（用户→优香→未花）每条消息最多两回复、共享群聊历史 + 独立角色人格、消息带发送者结构、成员列表可扩展、群聊 TTS、单聊完全隔离、不做长期记忆/RAG/自动聊天/社团系统。
- **实现（后端只增不改，前端复用 fragment 架构）**：
  - `backend/services/llm_service.py` 新增 `group_chat_stream/group_chat_complete`：共享群聊历史 + 每角色独立 system prompt（角色 prompt + 时间上下文 + 群聊说明）。历史转换：user 原样、**自己的历史消息不加前缀**（assistant 无前缀 = 我自己说的）、**其他成员加「[名字]：」前缀**（= 别人说的）——小模型模仿历史格式时自己消息无前缀，输出就不带前缀；本轮前面成员的回复同样转换追加；第二成员追加 user 指令（「某某刚刚已经在群里回复过了…请以 {name} 的身份自然地回应老师刚才的话」）让其接话而非续写他人；`group_chat_complete` 兜底剥离模型偶尔输出的「[名字]：」开头前缀。
  - `backend/main.py` 新增 `POST /api/group/chat`：接收 message + history + **members 列表**（参数化不写死），按 members 顺序循环生成；单个成员失败/角色不存在返回「⚠️ xxx 暂时无法回复」占位并继续下一个（不进后续上下文），不阻断。
  - `frontend/streamlit_app.py`：`GROUPS = {"yuuka_mika": {"name": "优香 × 未花", "members": ["yuuka", "mika"]}}`（扩展更多群只改这里）；`group_conversations` 独立存储（{group_id: [{role: "user"/"yuuka"/"mika"}]}）与单聊 conversations 完全分开；`render_chat_fragment` 改 key_base+mode 参数（单聊/群聊共用），群聊消息渲染角色头像 + 主题色名字标签 [早濑优香]/[圣园未花]；`render_group_page` 复用单聊页舞台/背景/信息条（立绘显示第一成员）；侧边栏「更多功能」群聊行从占位改为真入口（激活时高亮「群聊中」）；切角色/返回主页/开始聊天均清 current_group_id；路由群聊优先。
  - 共用函数提取（群聊页需要同样功能，非破坏性）：`render_chat_page_styles` / `render_character_info_bar` / `render_stage_and_background`——单聊/群聊页共用，单聊行为不变。
  - 群聊 TTS：每条角色消息独立 `<audio>`（src=/api/tts-audio?character_id={role}——端点本就按角色参数工作，零改动复用），仅最后一条自动播放（与单聊行为一致），voice_off 时不渲染 audio → 不发起合成；TTS 失败仅播放器无声，文字照常显示。
- **测试中发现并修复的 bug**：共享上下文强验证（告诉「我最喜欢粉色」→ 第二/三轮分别问优香/未花）时，优香回复输出「[早濑优香]：」前缀——小模型模仿了历史 assistant 消息的前缀格式，且带前缀回复进历史后污染循环。修复：①自己的历史消息不加前缀（其他成员才加）②system 说明改为「不带名字前缀的 assistant 消息是你自己之前说的」③生成后兜底剥离前缀。修复后两角色回复均无前缀、均答出「粉色」。
- **验证（后端 API 13/13 + 前端 Playwright 有头 15/15 + DOM 验证 + VLM 视觉确认）**：
  - 后端：群聊 200、恰好 2 条回复、顺序 yuuka→mika、非空；含不存在成员仍 200 且优香正常回复（占位「⚠️ 成员 not_exist_role 不存在」）；单聊 /api/chat 无回归；共享上下文强验证（粉色事实）两角色均答出。
  - 前端：优香/未花单聊正常；进入群聊（信息条「优香 × 未花」+「群聊 · 2 人在线」）；一条消息 3 条（user+[优香]+[未花]）顺序正确；5 秒后行数不变（无无限自动回复）；audio src 按角色绑定（yuuka/mika 都出现）；连续发送共享上下文生效；两角色头像不同；群聊消息未污染两个单聊（行数不变）；切回群聊历史保留、反复切换稳定（6 行不变）；发送后立绘舞台 y 坐标不变（无闪烁回归）；DOM 验证最后一条消息内容非空。
  - VLM 确认：群聊标识/名字标签（蓝紫 vs 粉）/独立头像/立绘/布局全部正常。
- **坑**：①群显示名初版用角色全名拼「早濑优香 × 圣园未花」，与规格的测试群名「优香 × 未花」不符——改 GROUPS 显式 name 字段；②本次环境 powershell Start-Process 被拦截（输出「进程已在后台启动」但进程未存活），改用 bash `(cmd &)` 后台方式启动成功；③9 条消息时截图 VLM 误报「最后一条气泡空白」——DOM 验证内容非空，为滚动区视口外裁切（正常滚动行为）。
### 33. 群聊节奏改造：等第一个人的语音生成完成后第二个人再开始回复（2026-10-11）
- **需求（用户提出）**：群聊 TTS 从「两条文字一起生成完再显示」改为**分步节奏**——优香回复 → 等优香语音生成完成 → 未花才开始回复（听到优香声音后未花接话，真实对话节奏）。
- **实现（仅改 frontend/streamlit_app.py，后端零改动）**：
  - 群聊发送改为**分步状态机**：`_do_send` 群聊分支只初始化 `_group_send_{key_base}` 状态（message/history/idx）并 append 用户消息；`_group_step` 每次 fragment 执行只生成**一个成员**的回复（复用 /api/group/chat，每次 members 传单元素、历史累积传递），完成后 `_wait_tts_done` 预热该成员 TTS（请求 /api/tts-audio 等响应 = 合成完毕写缓存），idx+1 后 rerun 进入下一个成员——消息逐步显示，未花在优香 TTS 完成后才生成。
  - `_wait_tts_done` 预热的顺序在 audio 元素渲染前（合成先写缓存 → rerun 渲染 audio 时 src 命中缓存秒回自动播放），**无并发重复合成**；仅最后一条自动播放不变；voice_off 时跳过预热直接顺序生成。
  - `_prepare_send` 加群聊防重入：分步未走完时忽略新发送（点击事件会在分步完成后排队处理）。
  - 「正在回复中」提示改为每步显示**当前成员名**（首轮优香、后续未花），比之前的「优香、未花正在回复中」更准确。
- **测试中发现并修复的问题（GPT-SoVITS 崩溃 + 超时链）**：
  - 首轮诊断：未花生成请求 300s 超时（「❌ 发生错误：HTTPConnectionPool... Read timed out」）、第二条优香生成 157s+ 未完成——排查：**9880 已挂（无响应）**、显存 7781/8188 MiB 几乎满载。根因链：**8GB 显存下 qwen(4.7GB) + GPT-SoVITS 权重反复切换（每次 set_model 重载 ~2.2GB）→ OOM 崩溃**；崩溃前 Ollama 生成也被显存压力拖慢（300s 超时），崩溃后显存释放生成恢复 0.33s。
  - 修复：①重启 GPT-SoVITS（9880 恢复 400）；②`_wait_tts_done` timeout 300→90s——TTS 挂掉/极慢时快速放弃不拖死文字流程（TTS 失败不阻断聊天，文字照常）。
  - 切页打断行为确认：分步生成中（fragment 阻塞在 TTS 预热）点切页按钮会**排队**（同步阻塞无法被 rerun 抢占），最多延迟 90s 后生效；打断后分步**完整恢复**（未花回复最终完成、state 清理干净、无重复生成）——属「等 TTS 完成才轮到下一个」需求的固有成本，功能正确。
- **验证（分步时序 7/7 + 回归 9/9 全过）**：
  - 时序：优香回复 14.0s 出现（生成 4s + TTS 预热 10s）、音频合成完成于 13.7s；未花回复 57.8s 才出现（gap 43.8s = 等优香 TTS + 未花生成）；合成顺序 yuuka@13.7s → mika@57.6s（mtime 证明）；无提示行残留。
  - 回归：优香/未花单聊正常；群聊一条消息两条回复（分步节奏）；无无限自动回复（3→3）；共享上下文生效；**群聊未污染两个单聊（2→2）**；群聊历史保留（6→6）；发送后立绘舞台 y 坐标不变（无闪烁回归）。
  - 切页打断诊断：群聊第一条分步 65.7s 完整、第二条优香 82.0s、切页打断后未花回复恢复完成、等 30s 无重复生成。
- **测试脚本坑（两次假阳性/误判，已修）**：①群聊已有标签时 `all(标签存在)` 立即 True → 假阳性，改用「未花标签计数增加」判定一轮完成；②分步生成中 fragment 阻塞 → 切页点击排队 → count 读到群聊页中间态误判「单聊被污染 2→5」，改切页后等 `.ci-name` 真正切换（最多 150s）再计数——修后 6a/6b 均 2→2 PASS，证明数据隔离从未有问题。
- **已知限制**：①8GB 显存下群聊每轮优香↔未花两次 set_model 权重重载（各 ~40s）→ 单轮全链路约 60-100s，属 GPT-SoVITS 固有成本；②连续高频使用 GPT-SoVITS 有 OOM 崩溃风险（显存满），挂掉后聊天正常、语音静默失败（90s 超时放弃），需手动重启 GPT-SoVITS。
### 34. 群聊生成逻辑修复：角色自说自话/多轮模拟 + speaker label + 深夜时间失效（2026-10-11，用户实测反馈）
- **用户实测发现的两个严重问题**：①一条角色消息内部出现「[圣园未花]：……[早濑优香]：……[圣园未花]：……」——模型自己模拟了优香→未花→优香多轮对话塞进一条消息；②23:30 测试角色回复「老师，今天您吃的是营养早餐吗？」——时间上下文未影响行为。
- **根因 1（自说自话/多轮模拟）**：原结构把共享历史转成**连续多条 assistant 消息**（`assistant: [优香]：xxx` + `assistant: [未花]：xxx`）——qwen chat template 把连续 assistant 块理解为「一个 assistant 的多段输出」，模型续写时便模仿输出多段（模拟多轮角色对话）；结尾指令「（优香刚刚已经在群里回复过了……请以未花的身份回应）」也鼓励模型继续演。
- **根因 2（时间失效）**：时间上下文在 system prompt 中间（角色 prompt + 时间 + 群聊说明）——群聊说明在末尾抢注意力，7b 小模型对长 system 的时间遵守变差；且缺少时间段行为引导（模型不知道深夜提到吃饭应是夜宵）。
- **修复（仅改 backend/services/llm_service.py，前端/TTS/SoVITS api.py 零改动）**：
  - **消息结构根治（方案 Z）**：`group_chat_stream` 重写——把整个共享历史渲染成**一条 user 消息里的「群聊记录」文本**（`老师：xxx` + `[名字]：xxx` 纯文本行），每次请求都是 system + 单条 user，**assistant 位置永远只有模型自己的回复**——结构上消除多轮模仿诱因（模型无从「续写剧本」，历史前缀只是文本记录非 assistant 格式）；单聊 chat_stream 原样未动。
  - **system prompt 重排**：`角色 prompt + 群聊回复规则（新 _group_note，6 条硬规则：只输出自己的一句回复/禁任何 speaker label/禁替他人说话/禁多轮剧本）+ 时间上下文（移到 system 末尾，离生成位置最近、注意力最强）`。
  - **user 任务带当前时间**：`现在时间是 {HH:MM}，请结合当前时间段理解老师的场景`——时间同步到生成位置。
  - **_time_context 加时间段行为引导**（单聊也受益、无破坏）：深夜（23 点后）提到吃饭应是夜宵/晚餐、清晨是早餐、中午是午餐，绝不要把当前场景理解成与时间段不符的时段。
  - **生成层防护清理 `_sanitize_group_reply`**（兜底，不依赖模型自觉）：剥掉模型违规输出的开头 speaker label；正文中间（换行后）再出现任何 speaker label 即截断（= 模拟多轮的起点）。label 候选由 `_group_speaker_pattern` 动态生成：全部角色全名 + 名（name[-2:]）+ id + 老师——新增角色自动纳入。
  - **GROUP_MAX_TOKENS=150**：群聊单条回复生成上限（min(角色配置， 150)）——限制多轮模拟空间 + 加速（一到两句 ~100 token）。
- **验证（后端双路径 + 前端端到端，12/12 全过，当前 23:37 深夜实测）**：
  - 双元素路径（main.py 循环）测试 A/B/C/D 5/5：**A 时间**——3 轮 6 条回复全深夜场景（「都这么晚了还工作」「夜宵」「早点休息」），**零早晨/早餐违规**；**B 单角色输出**——3 轮 6 条全无 speaker label、无多轮模拟；**C**——连续 3 轮每轮恰好 2 条、全程无 label；**D**——两角色都记得「粉色」。
  - 单元素路径（前端 _group_step 等价，members 传单成员 + 历史累积）4/4：深夜场景零违规、无 label、上下文共享（两角色都答出粉色）、全程无 label。
  - 前端 Playwright 端到端 3/3：群聊一轮两条回复；**气泡正文无多角色混合**（[早濑优香]\n老师今天还在忙吗？晚餐吃了没？——深夜场景正确）；切换后历史保留、单聊干净。
- **遗留观察**：模型偶尔会说「现在这个时间……」（轻机械提时间，规则允许在时间与话题相关时提及）；mika 偶尔回复偏长（3+ 句）但 max_tokens 150 上限内、无 label/多轮。
### 35. 群聊小幅优化：明确点名角色时该角色优先回答（2026-10-12）
- **需求（用户提出）**：「优香，你今天在做什么？」→ 优香先回复未花补充；「未花，你准备的夜宵是什么？」→ 未花先；不点名保持默认 优香→未花；同时点名两人按出现位置排序。要求：简单可靠字符串匹配（无 AI 意图识别）、无法判断用默认顺序、只改回复顺序不改最多两条回复规则、不碰上下文共享/独立 prompt/TTS/单聊/群聊架构。
- **实现（仅改 frontend/streamlit_app.py，后端零改动）**：
  - 新增 `_member_aliases(member_id, characters)`：成员称呼候选 = 全名 + 名（name[-2:] 简称，早濑优香→优香）+ id——动态从 /api/characters 生成，新增角色自动纳入。
  - 新增 `detect_mention_order(message, members, characters)`：对消息（lower 统一大小写）按每个成员称呼**首次出现位置**匹配——只点一人该人排首；同时点名多人按出现位置排序；未点名成员保持默认顺序排后；无点名返回原顺序。
  - `_do_send` 群聊分支：初始化分步状态机时 state 增加 `members` 字段（重排后顺序）；`_group_step` 与「正在回复中」提示改从 `state["members"]` 取当前成员（兜底 group_members()）。
- **测试中发现并修复的测试 bug（功能从未有问题）**：`send_group_and_wait` 原以「未花标签计数 +1」判定一轮完成——点名未花时未花是**第一条**回复，+1 时一轮才完成一半 → 检测提前返回、误报「[未花][未花]」+ rows 12≠9。实际 rows=12 = 4 轮完整（优香第二条最终生成）、轮 2 顺序 [未花, 优香] 恰证明点名未花生效。修为「行数 +3 且末条非提示行」的通用判定后 6/6 全过。
- **验证（单元 13/13 + 端到端 6/6 全过）**：
  - 单元（纯函数直测）：点名优香（句首/句中）、点名未花（句首/句中）、不点名 ×2、同时点名（优香前→优香先/未花前→未花先）、自然称呼（优香酱）、英文 id（Yuuka/mika 大小写不敏感）、全名点名、无点名（含其他词）——13/13。
  - Playwright 端到端：点名优香→[优香]先[未花]后；点名未花→[未花]先[优香]后；不点名→默认[优香]先；同时点名（优香在前）→[优香]先；单聊回归正常；群聊历史保留（12 条 = 4 轮完整）。
### 36. 群聊生成优化：当前用户消息最高优先级（修复复用上一轮回复/旧关键词跟随）（2026-10-12，用户实测反馈）
- **用户实测问题**：①「未花，你觉得优香刚才说得对吗？」→ 未花直接重复上一轮自己的回复，没回答当前问题；②切换话题后角色仍围绕上一轮关键词继续回答。
- **根因**：历史 transcript（user 消息内、生成位置很近）占小模型注意力大头，当前问题被稀释——模型从 transcript 里抄语义最近的旧回复（此前逐字 100% 相同）/ 继续旧关键词。
- **修复（仅改 backend/services/llm_service.py，3 步实测迭代；前端/TTS/SoVITS api.py/单聊/点名顺序/共享历史存储零改动）**：
  - `_group_note` 加优先级原则（7-9 条）：先只关注当前用户的新问题（明确要求什么、在问谁）、历史只作背景不能代替当前任务；禁止复用自己上一轮回答、切换话题立即跟随、不因关键词频率高就围绕它；回应成员不等于重复。
  - **user_content 结构迭代**（实测驱动）：
    1. 第一版：user 里加【你上一条自己的回复】全文 + 禁复用——**实测反面效果**：小模型看到上一条回复全文反而逐字复制（优香第 3/4/5 条回复完全相同×3），负面引用诱发复用；
    2. 第二版：去掉上一条回复全文展示（只留任务里「禁止复用你自己之前说过的句子」）——优香完全改善，未花仍抄 transcript 里语义最近的旧行（80-85% 相似）；
    3. 第三版（定案）：**transcript 移入 system prompt（背景资料，远端）+ 时间上下文仍在 system 末尾；user 位置只放【当前用户的新问题（最高优先级，只回答这个）】+【你的任务】**——生成位置附近只有当前问题，小模型注意力不被历史稀释（结构上防复用）。
  - 判定标准：相似度阈值 0.9（逐字相同才算真复用；措辞不同、综合上下文针对当前问题的相似回答属小模型语义收敛，可接受）。
- **验证（7/7 全过，23:5x 深夜实测）**：
  - 1 基础回答：两条非空 ✓；
  - 2 优香评价未花：sim=0.0（未重复自己上一轮）✓；3 未花评价优香：**「优香担心老师的身体嘛，早点休息真的对身体好哦」——真正回答当前问题、针对优香的观点**，sim_max=0.05 ✓（此前是直接重复自己旧回复）；
  - 4 话题切换「算了，不说这个了。你们明天有什么安排？」：两角色均提「明天」（新话题跟随）✓；
  - 5 连续上下文渐进（今天工作很多→晚饭也没怎么吃→但是现在不困→明天也没什么重要事情→所以你们觉得我现在应该怎么办？）：**每条消息都得到针对性回复**——「工作多→先处理重要的事剩下明天做」「没吃晚饭→帮你准备夜宵」「不困→先聊聊天」「明天没事→早点休息」「应该怎么办→综合上下文给建议」，重复 0/2 ✓（此前优香第 3/4/5 条逐字相同）；
  - 全程无 speaker label、无多轮模拟（防护清理持续生效）。
- **重要经验（防重复机制设计）**：给小模型的「禁止复用 X」若同时展示 X 的全文，负面引用反而成为复用源——防重复应靠**结构**（旧内容放远/不放）而非「展示全文+禁止复用」的组合。
### 37. 群聊/单聊意图理解修复：优香答非所问+无故说晚安+质疑不修正（2026-10-12，用户实测反馈）
- **用户实测问题**：用户说「补作业补了两个小时」并问两个角色今天过得怎么样——优香最初没回答问题；用户提醒后优香回答了却突然追加「我也得赶紧休息一下了。晚安哦」；用户连续追问「唉？晚安？优香是要睡觉了吗？」「就是说啊，优香这么早睡吗？」——优香反复说「早点休息」「晚安」，不解释也不根据质疑修正。
- **根因定位（真实对话在群聊/单聊对照实测）**：
  - A. **_time_context 深夜引导过度（直接根因，单聊/群聊共享层）**：第 36 次迭代为修「早餐」问题加的「深夜……提到休息很正常」被模型泛化成「深夜就该主动聊休息」——实测单聊也出现劝休息/夜宵/晚安倾向，单聊/未花同为污染源；
  - B. **_group_note 缺「质疑/纠正/反问」处理规则（群聊层）**：用户质疑时无指引，模型重复原话或顺关键词（「晚安」）坚持；
  - C. **群聊任务指令对多成分消息拆解不足**：「我今天补作业两小时，你们今天过得怎么样？」——模型把背景当重点、没先回答问句；
  - prompt.txt 本身不是主因（单聊第 1 问实测表现正确证明 prompt 能正确回应）。
- **修复（仅改 backend/services/llm_service.py，纯提示词 3 处；prompt.txt/前端/TTS/SoVITS api.py/点名顺序/共享历史存储零改动）**：
  - _time_context：深夜引导改中性——删「提到休息很正常」（泛化源），改「深夜提到吃饭指夜宵、清晨指早餐、中午指午餐；时间只是背景，不要因时间段就主动把话题转向休息、睡觉或劝老师休息，更不要无缘无故说晚安」（对单聊/未花是共同修复，实测证明它们同样被污染）；
  - _group_note 加第 10 条：用户质疑/追问/反问时先理解质疑什么，再解释或修正——不重复刚才的话，也不顺着质疑里的关键词继续坚持；
  - group_chat_stream 任务指令加：新问题里有问句时先回答问题本身（问句问你就回答你自己的情况），再回应其他内容。
- **回归测试（真实对话序列 ×3 跑，完整打印全部输出不挑结果，23 点后深夜实测）**：
  - **已修复**：①第 1 问答非所问——群聊 2/2 轮优香均回答自己情况（「那我这边还算顺利，就是有点小忙碌」「最近我在研究新的预算方案，挺忙的」）、不再「喝热牛奶」；单聊正确回答「优香今天还好啦……心情挺不错的」；②编造情景——不再编「老师好晚才休息」；③质疑解释——群聊 1 质疑后优香「诶？老师是在关心我吗？不过我还挺精神的」、追问后「其实我是刚有点小忙碌才休息的啦」——**先理解质疑再解释**，符合目标；单聊质疑后「我还挺精神的」、追问后反问澄清「优香是打算早点睡呢，还是也在忙碌着什么？」——**完全符合**。
  - **残留（如实汇报）**：群聊质疑追问后优香仍带「晚安」（解释了原因但没放弃晚安行为）——深夜 23:5x 说晚安本身是合理行为（时间确实快十二点）；且群聊里「晚安」被**多成员互相强化**（优香说晚安→未花跟说→transcript 里多次→继续锚定），群聊 2 第 2/3 问优香回复还出现重复（「真是的……先早点休息吧」×2）。这是群体接话放大话题的结构特性，prompt 只能缓解（自动判定 2 项疑似：群聊 1/2 质疑后坚持晚安 2/2）。
- **结论**：核心问题（答非所问/编造情景/质疑不解释）已修复；「晚安」在深夜语境属合理行为+群体接话强化，是否进一步调整（如群聊 prompt 更强约束晚安类收尾语）待用户判断。
### 38. 规则精简重组：明确请求直接执行 + 澄清后不拉回旧话题 + 日常活动设定（2026-10-13，用户实测对话反馈）
- **用户真实对话暴露的四个问题**：①明确要求推荐且说「没想好」时优香仍反问偏好；②连续三次澄清「今天早上在学院里干什么/聊天前在干什么」优香仍拉回午餐话题甚至把问题抛回用户；③优香把聊天中的行为（和未花讨论午餐）当成聊天前的经历（未花反而能给出茶会活动）；④跨轮重复既有内容（「有没有什么特别喜欢的菜肴」隔 3 轮逐字重现）。
- **根因分析结论（代码依据）**：任务指令只覆盖问句不覆盖祈使请求；_group_note 第 8 条只防「上一轮」不防跨轮；优香 prompt.txt【帮助老师】的「先问」模式（「不过老师得先告诉我是什么工作吧？」）被泛化；【不要编造情景】只约束老师不约束角色自己、两角色均无日常活动素材；优香 system 总长（346 行 + 10 条规则）稀释遵循度（未花 97 行 + 【输出铁律】置顶表现更稳，对比证实）。
- **修复（精简重组不叠加，仅改 backend/services/llm_service.py + 两个 prompt.txt；前端/TTS/api.py/点名顺序/历史存储零改动）**：
  - `_group_note` **10 条 → 4 条重组**（覆盖全部优先级）：①身份+只输出台词本身；②禁 label/替他人说话/多轮剧本；③**当前新问题最高优先级 + 意图分层判断**（明确请求→直接执行给出具体内容、老师说没想好要求推荐时直接给方案不反问偏好；问句→先回答问题本身；质疑/纠正/澄清→以最新澄清后的意图为准、解释或修正、不拉回旧问题或反复出现的内容；判断不出→自然回应）；④禁止复用之前**任何轮次**的没必要重复内容、切换话题立即跟随。
  - `group_chat_stream` 任务指令精简（优先级判断移入 _group_note，指令去重）。
  - 优香 prompt.txt：【帮助老师】改写——「先问」模式限定（明确说了「就交给你了」「我来决定」「帮我推荐一下」就直接给具体方案，不要先问偏好；偶尔澄清可以，说清楚的部分不重复问）；新增【你自己的日常】（上课/研讨会事务/同学活动的身份相符范围；问起今天/早上/聊天前在做什么时给自然回答，不精确到分钟、不每次一样、不把当前聊天话题当成聊天前经历）。未花 prompt 对称加【你自己的日常】（上课/茶会活动/朋友）。
- **回归测试（同一脚本 3 次运行，完整打印输出不挑结果；注意小模型随机性大，跨轮统计）**：
  - **稳定改善（3/3 次均过）**：①群聊明确请求（「推荐一下午餐吧，我没什么想法，帮我决定」）→ 两角色都直接给出具体食物推荐（鸡肉沙拉/牛肉炒饭/意大利面等），不再只反问等答案；②「吃不饱」→ 承认+给新方案（主食加小菜/搭配水果汤），不再辩解原方案；③**连续三次澄清（核心案例）→ 优香每次都回答聊天前的活动**（「上完课后去了研讨会处理事务」），三次不拉回午餐、不把问题抛回用户（此前完全失败：拉回+抛回）；未花给出活动（上课/茶会）；④多轮 0 逐字级重复（sim<0.9）；⑤单聊「吃不饱」后给完整方案（牛肉盖饭/咖喱）。
  - **随机残留（跨轮统计，如实汇报）**：①单聊明确请求的「直接给推荐」遵循约一半概率（3 次运行 1 次反问偏好——单聊无 _group_note 强化，prompt 稀释仍在）；②优香群聊推荐常带反问开头（「想吃点什么呢？」）但都跟了具体推荐（半执行半反问）；③新发现：同输入下**两角色回复内容趋同**（某轮优香/未花对「明天想出去玩」给出逐字相同的回复）——人格独立性在内容层面弱化（sim 判定只查自己旧回复、不查对方，未计入判定）。
- **判定脚本坑（本轮自查修了 3 处）**：FOOD_WORDS 缺「水果/意大利/轻食/餐厅」误判无推荐；「只有反问无回答」才该算抛回问题（先回答后承接反问是正常聊天，初版过严误伤）；dict 解包 KeyError（第 3 次犯同类错）。
### 39. 意图触发意图化 + 集体指代 + 观点立场人格独立（2026-10-14，对照实验驱动）
- **四个问题的根因分析结论（对照实验 + 代码链核实，未预设答案）**：
  - 请求先问偏好：_group_note 第 3 条与 prompt.txt【帮助老师】的触发条件均为**列举式**（「没想好」「就交给你了」「帮我推荐一下」）——「有什么建议」不在条件内，规则未激活（已证实）；优香反问后其实给了建议（半执行半反问）（已证实）；
  - 问自己经历先反问老师：两份 prompt 均鼓励反问（优香【主动聊天】、未花【与老师的关系】）；_group_note「问你就答你自己的情况」未覆盖「你们/各自」集体指代（已证实）；
  - 论证/措辞高度一致：**对照实验（A 优香单独/B 未花单独/C 未花含优香历史）证实 sim(A,B)=0.0、sim(A,C)=0.0——措辞级完全不相似，此前观察的「逐字相同」是同输入两次生成的随机收敛，非系统性锚定；字符级相似度指标对立场趋同失效**（已证实）；但**立场层面锚定确实存在**：未花单独（B）明确主张随性 → 含优香历史后（C）变成「两种方式都有它的魅力」平衡答案，自己的立场被中和（已证实）；两份 prompt 均无「观点题表达自己立场」指引，人设性格未链接到观点表达（已证实）；
  - 第二名生成时上下文包含第一名回复：**代码链证实**——前端 _group_step 的 prev_replies → history_for_backend → 后端 transcript → system【群聊记录（背景资料）】；锚定在立场层不在措辞层（实验区分，推翻了仅凭输出相似的归因）。
- **修复（精简重组，_group_note 保持 4 条；仅改 backend/services/llm_service.py + 两个 prompt.txt）**：
  - _group_note 第 3 条：请求触发条件从列举式改**意图式**（「征求建议、要求推荐、帮忙或出主意时——先给出具体内容，必要时再在最后补一句询问；不要先反问偏好再等老师回答」）；加集体指代条（「问『你们』『各自』的经历/感受/情况时——先回答你自己的部分再考虑是否反问；不要用反问老师代替回答」）；
  - _group_note 第 4 条并入观点立场（「被问观点或偏好时按自己的性格给出真实倾向，不要中立和稀泥，也不要把对方刚说的观点原样复述成自己的」）；
  - 优香 prompt.txt：【主动聊天】「老师问你的问题先回答自己的部分，然后再自然地反问老师——不要用反问来代替回答」；【性格】计划倾向（「被问计划/安排类话题通常倾向提前规划、关注安排和实际可行性——不是死规矩，朋友拉你临时起意也会纠结着答应」）；
  - 未花 prompt.txt：【角色特点】随性倾向（「倾向随性一点、享受当下和意外惊喜——但有自己真实的想法会独立表达，不是为了和谁唱反调，也不会因为别人意见不同就马上改口」）。
- **回归测试（同一脚本 2 次运行，完整打印输出；模型在 F 盘首次调用冷启动约 2 分钟属正常）**：
  - **稳定改善（2/2 次均过，核心目标达成）**：**观点题人格独立性——优香群聊立场与单独立场一致（「提前规划可以有让人心里有底/让事情更有条理」规划为主）、未花群聊立场与单独立场一致（「我觉得随性一点挺好啦」随性为主）——未花在含优香历史时不再被中和成平衡答案（对照实验里此前的失败形态消失）**；
  - 未花回答顺序达标 2/2：「我今天最开心的事情就是和老师聊天♪老师呢？」——先答自己再反问；「去市区逛逛街怎么样？♪晚上还可以吃点好吃的」——先给建议；
  - **系统性残留（2/2 次持续，如实汇报）**：**优香群聊「先反问老师/偏好」的模式 4/4 次持续**——「老师有什么想去的地方吗？」「老师想去哪里？市区还是周边游？」「老师今天过得怎么样？我今天在研讨会上帮着整理了一下资料」（先反问再答）——调用路径分析：反问引导是多源叠加——①优香 prompt.txt【语气参考】在 prompt **末尾**（注意力强位置）且示例多为反问（「今天怎么样？」）；②任务指令是**间接引用**（「先按系统提示里的群聊回复规则判断」）而非直接写明；③transcript（system 背景）里老师消息占大头。非单一提示词长度问题。
  - 随机波动：优香测试 1 一次给了条件性建议（「如果没有特别想去的，我可以推荐几个公园或商场」）、一次完全只反问（「老师想去哪里？市区还是周边游？」）——执行程度随机；未花建议顺序一次达标一次建议性问句在前（判定词表漏检建议性问句）。
- **下一步方向（待用户判断）**：任务指令改为**直接写明**回答顺序（user 位置遵循度最高，不再间接引用「按系统提示里的规则」）；或精简【语气参考】的反问示例。
### 40. 优香「先反问后回答」最小修复：任务指令间接引用→直接写明（2026-10-14）
- **修改（仅 backend/services/llm_service.py 群聊任务指令措辞；_group_note 4 条结构/两个 prompt/语气参考/前端/历史拼接/采样参数/TTS 零改动）**：任务指令从间接引用（「先按系统提示里的群聊回复规则判断意图」）改为**直接写明回答顺序**四条：老师提出问题时先回答问题本身；问「你们」「各自」或个人经历时先回答自己的部分；征求建议/推荐/帮忙/出主意时先给出至少一个具体建议、不要先反问偏好并等待回答；回答完再自然反问（可选），反问不能排在回答之前、不能代替回答。不禁止所有反问，不要求每条回复都反问。
- **回归测试（三题 × 3 次生成 + 观点题单独基线 ×3，完整输出已打印；模型在 F 盘首次调用冷启动约 2 分钟属正常）**：
  - **达标部分**：未花随性立场 **3/3 稳定**（「我觉得随性一点更好哦～这样可以随时抓住意外的惊喜」）；优香「先建议后反问」形态在 R3Q1 出现（「明天出去玩是个好主意呢。最近天气不错，可以考虑去公园野餐或者逛逛街。老师对哪里感兴趣些？」）；**R1/R2 的建议请求里反问不再等待回答**（「老师想去哪儿呢？要不我们去附近的公园散散步？」——反问后立即给出建议，阻塞形态消失）；R3Q2 优香先答自己（「今天最开心的事情就是和大家一起讨论了新项目」开头、无反问开头）。
  - **未解决（如实汇报）**：①优香「先反问」开头模式在 Q1 2/3、Q2 2/3 持续（R1/R2Q2「老师今天过得怎么样？」反问开头后才答自己）——任务指令直接写明后遵循度仍有限（约 1/3 完全达标，比此前 0/4 有改善但未根本解决）；②判定词表误判 2 处：R3Q2 实际达标被误判（「讨论/新项目」不在经历词表）、Q3 优香立场词表误判（R2/R3 优香实际主张随性「计划总是容易出意外的嘛」但含「规划」词被判规划立场）；③**新观察：Q3 两角色趋同**——R2/R3Q3 优香与未花说几乎一样的话（「计划总是容易出意外的嘛」），优香的规划立场 2/3 次反转为随性（上一轮 2/2 稳定，本轮 1/3）——立场稳定性随机波动大。
- **结论**：任务指令直接化带来部分改善（反问不再阻塞建议、约 1/3 完全达标），但优香「先反问」习惯未根治；立场稳定性随机波动大。剩余手段（改 prompt.txt 删反问示例 / 多方案投票采样 / 提高 temperature 约束外的结构手段）超出本轮范围，待用户判断。
### 41. 优香 prompt 语气参考重写：顺序示例替换反问示例（2026-10-14，仅改 characters/yuuka/prompt.txt）
- **检查结论**：原【语气参考】7 组示例中，唯一反问老师的示例（「下午好」→「今天怎么样？」）是「回应完就反问」模式的来源；示例 4（真可爱）与示例 3（心情变好）重复；**缺少目标顺序的示例**——模型从示例里学到的就是「简短回应+反问」。【性格】规划倾向改为「默认倾向+这是你自己的判断、不因别人提出不同方案就跟着改口；场景确实适合随性时给出符合情境的理由」。
- **修改（仅 characters/yuuka/prompt.txt；代码/群聊历史拼接/采样参数/未花 prompt 零改动）**：【语气参考】重写——删示例 1（反问结尾）与示例 4（重复夸奖），保留 5 组核心（打招呼/害羞/劝休息/帮助/吐槽帮忙），**新增 3 组顺序示例**：征求建议→先给具体建议（水族馆/商场）、问个人经历→先讲自己再问老师（解题/老师呢）、问观点→先表达判断再补充理由（倾向规划/纯粹放松时随性没关系）；加「示例只用于体会语气和回应顺序，不要照抄句子」。
- **回归测试（单聊/群聊 3 题 × 3 次 = 18 次生成，完整输出已打印，人工复核语义）**：
  - **群聊 9/9 全 PASS**：Q1 3/3 优香先给具体建议（「水族馆怎么样？最近有个特别展」建议性问句含建议）；Q2 3/3 先答自己（「我今天解了一道难题挺开心的」「我今天最开心的事情是在研讨会里找到了一个我一直想研究的主题」）；Q3 3/3 规划倾向稳定（「我倾向提前规划，至少先把交通和大致行程定下来，玩起来不会手忙脚乱」——3 次一致，**不再被未花的随性立场中和**）。
  - **单聊自动判定 3/6，人工复核后语义全达标**：Q1 3/3 先给建议 ✓；Q3 3/3 规划倾向稳定 ✓；Q2 3 个 FAIL 全是「我吗？」的误判——**「我吗？」是自语式确认语气（2 字，非向老师提问），后面紧跟回答自己**（「我吗？今天上课的时候解开了一道很难的题，挺有成就感的。老师呢？」）——符合「先讲自己再问老师」的语义，判定按「问句前有内容」误伤。
  - **核心结论：单聊+群聊三题全达标（先建议 6/6、先答自己 6/6、规划倾向稳定 6/6）**——优香「先反问、后回答」的持续问题（上一轮 4/4 次持续）经示例顺序重写后根治。
- **新观察（如实）**：优香单聊 Q1 输出「水族馆怎么样？最近有个特别展，不会太累也能逛得开心」与新示例**几乎逐字一致**——模型照抄示例，3 次建议内容固定相同（水族馆+特别展）——优香 prompt 缺少未花那样的「不要照抄示例里的句子」说明；建议内容多样性受损，待后续判断是否补一句。
### 42. 设置页模型切换功能：自动检测 Ollama 模型 + 前端一键切换（2026-10-16）
- **功能（后端 + 前端；聊天架构/单聊架构/TTS/prompt/采样参数零改动）**：
  - 后端：`llm_service` 加 `overridden_model` 内存覆盖（重启后端恢复各角色 character.json 默认）+ `set_model()` + `_effective_model(char_cfg)`（有覆盖用覆盖、无覆盖用角色默认），`chat`/`group_chat` 的 payload 改用 `_effective_model`；`main.py` 加 `GET /api/models`（代理 Ollama /api/tags，返回 models + current）和 `POST /api/model`（空字符串 = 恢复默认）。
  - 前端：`render_settings_page` 从占位改为真功能——进入页面拉取模型列表，显示当前生效模型，下拉选择（含「（使用各角色默认）」）+「切换到该模型」按钮；「未来计划」列表删去「API 模型切换」。
- **测试踩坑（Playwright + Streamlit，两处假阴性/真 Bug）**：
  - **testid**：Streamlit 1.63 中 `st.success` 渲染为 `[data-testid="stAlert"]` 而非 `stSuccess`——初版测试找错元素导致切换明明成功却判 FAIL（假阴性）；「恢复默认」的 PASS 是误判（`b:has-text("各角色默认")` 命中的是顶部状态行残留旧值，实际 POST 未按预期发出）。
  - **真 Bug（selectbox 动态 index 重置用户选择）**：`index` 参数跟随后端 current 每次重算——后端 current=qwen3:8b 时进页面下拉默认选中 qwen3:8b（不碰下拉直接点按钮会 POST qwen3:8b）；用户手动选择后点按钮触发的 rerun 用动态 index 重置下拉，选择丢失、POST 错误模型。**修复**：`st.session_state.model_pick` 固定用户选择（首次进入按 current 初始化一次），selectbox 传 `key="model_pick"` 不传 index。
  - Streamlit selectbox 下拉选项渲染在 body 级 Portal，须用全局 `[role="option"]` 定位而非容器内定位。
- **回归测试（Playwright 有头 8 项，每步同步验证后端 current；切换→恢复→再切换 qwen2.5→再恢复全链路）**：8/8 PASS——下拉含全部已下载模型（qwen3-vl:8b / qwen3:8b / qwen2.5:7b-instruct-q4_K_M）+ 默认项；切换 qwen3:8b 提示 + 后端生效；恢复默认提示 + current=None；切换 qwen2.5:7b 同样正常；收尾后端归位默认。临时测试脚本与截图已清理。
- **遗留观察（待用户换模型重测群聊三题验证）**：优香单聊建议输出与新示例几乎逐字一致（「水族馆特别展」×3）——优香 prompt 缺少未花那样的「不要照抄示例里的句子」说明，建议内容多样性受损。
### 43. 切换 qwen3:8b 后单聊超时 + 回复变怪：关闭思考模式 think:false（2026-10-16）
- **现象**：设置页切到 qwen3:8b 后，先与优香对话、再与未花对话报 `Read timed out. (read timeout=120)`；未花回复内容奇怪（答非所问/截断感）。后端日志所有 POST /api/chat 均为 200——后端未挂，是响应耗时超过前端 120s read timeout。
- **根因（Ollama 实测确认）**：qwen3 系列默认开启思考模式，且 Ollama 将思考内容放在独立 thinking 字段（不污染 content，流式同理）——但带来两个问题：①思考 token 计入生成时间：8 字打招呼消息裸测 17-20s（thinking ~500 字 + 回复 ~40 字），长 prompt 实际对话更久 → 超过前端 120s 超时；②**思考 token 与正式回复共享 max_tokens 配额**（实测 max_tokens=350 时 thinking 506 字 + 回复仅 39 字）——复杂对话下思考吃光配额、正式回复被腰斩 → 「回答变怪」。群聊 GROUP_MAX_TOKENS=150 下更严重。
- **修复（仅 backend/services/llm_service.py 两处 payload 加 `"think": False`；采样参数/消息结构/prompt/前端零改动）**：单聊 chat_stream 与群聊 group_chat 的 Ollama payload 均加 think:false 关闭思考模式。兼容性实测：qwen2.5:7b-instruct（非思考模型）传 think:false 正常返回不报错、qwen3:8b 返回无 thinking 字段——三模型均安全。
- **验证（重启后端后，current=qwen3:8b）**：未花单聊 2.9s（66 字完整回复）、优香热状态单聊 3.9s（97 字完整回复，先答自己再反问）、群聊 5.4s 两成员正常（优香「这周末我打算好好休息一下……老师呢？」、未花「我想和老师一起出去走走哦～」——均先答自己）；关闭思考后速度与 qwen2.5 持平（此前同场景 17-20s）。
- **遗留风险（未处理，待用户定夺）**：优香第一次调用 137.3s 为 qwen3:8b 冷启动（模型加载约 2 分钟，属正常），但**仍超过前端 120s read timeout**——切换到从未加载过的模型（如 qwen3-vl:8b）首次对话时前端仍会报一次超时，重试即可；如需根治需调大前端 timeout（涉及前端参数，待用户确认）。
### 44. 模型生命周期与失败消息处理最小修复：预加载 + keep_alive=-1 常驻 + 错误不进历史 + 群聊卡死根因定位（2026-10-17）
- **修改文件与关键逻辑**：
  - `backend/services/llm_service.py`：模型选择持久化到 `backend/data/model_state.json`（_load_state/_save_state，重启后端自动恢复）；`effective_model_now()`；预加载体系——`start_preload()` 创建 asyncio 后台任务（快速连续切换时 cancel 旧任务防竞争）、`_preload_model()` 先查 /api/ps 已加载则跳过（不把「请求已发出」当「已加载」，以 /api/ps 确认）、HTTP 非 200 抛错记 failed、`_unload_model()`（keep_alive=0）切换时卸载旧模型防 8GB 显存双模型驻留、`preload_status()` 快照（loading/ok/failed + detail）；单聊/群聊 payload 加 `"keep_alive": -1`（模型常驻不过期）。
  - `backend/services/tts_service.py`：translate payload 加 `"keep_alive": -1`（不带 keep_alive 的请求会把常驻模型的过期时间重置回 Ollama 默认 5 分钟）。
  - `backend/main.py`：startup_event 触发预加载（不阻塞启动）；POST /api/model 切换后触发预加载；GET /api/models 返回 preload 状态；群聊 replies 每项加 `ok` 字段（失败回复不进 turn_replies，即不进后续成员上下文）；TTS 翻译模型改用 `llm_service._effective_model`（跟随生效模型，防翻译拉起第二模型驻留挤爆显存）。
  - `frontend/streamlit_app.py`：`send_chat_message`/`send_group_message` 改结构化返回 (ok, text[, replies, err])，异常显式区分 Timeout/ConnectionError/其他（不靠字符串前缀判断）；`_do_send` 单聊失败不 append assistant、错误存 `_send_error_{key}` 只渲染不进历史；`_group_step` 请求级失败终止分步状态机、成员级失败（ok=False）不写历史不进 prev_replies 不做 TTS 等待、不阻断后续成员；`_prepare_send` 新一轮发送清旧错误；fragment 消息区渲染错误行（❌ 红底 UI 行，纯展示）；设置页显示预加载三态（加载中/已就绪/失败原因）。
- **验收测试（8 项，实测证据）**：
  1. 冷启动自动预加载 ✅（默认 qwen2.5 与恢复 qwen3:8b 两种场景，/api/ps 确认驻留、expires_at=2319 年）
  2. 预载后首条消息无冷启动 ✅（单聊 4.1s / 群聊 4.9s）
  3. 空闲 320s 模型仍驻留 ✅（keep_alive=-1 生效，不再出现「隔 5 分钟再聊必冷启动」）
  4. 重启 FastAPI 模型驻留不重复加载 ✅（「已在内存，跳过预加载」+ 聊天 1.4s 可用）
  5. 切换模型用新模型 ✅（qwen3:8b 生效 + 旧 qwen2.5 keep_alive=0 卸载）
  6. 失败不进历史 ✅ **10/10 PASS**（单聊/群聊失败：错误行显示 + user 保留 + 正式回复 0；恢复后：单聊 user=2+assistant=1、群聊 user=2+成员回复=2、错误行清除）——**注意：本项前两轮 7/10 的失败均为测试脚本竞态 Bug 而非应用 Bug**（详见下条）
  7. 预加载失败状态 ✅（qwen99:fake → preload failed + 「Ollama HTTP 404」，API/日志/UI 三层验证）
  8. 显存 ✅（单模型驻留 7643/8188 MiB；切换时旧模型正确卸载）
- **群聊「卡死」根因定位（非本轮代码回归，既有资源冲突）**：语音开启时群聊分步等待 TTS（_wait_tts_done 每成员一次）——GPT-SoVITS 合成需 set_model 切权重，**yuuka v2 与 mika v4 两套权重每次来回全量重载**（日志「Removing weight norm... loading vocoder」），单次 TTS 全链 60-120s；且 **mika v4 权重与 qwen3:8b 常驻（5.5GB）显存冲突（8GB 卡装不下）**——冲突后 Ollama runner 退化（POST /api/chat 从 1-2s 恶化到 1m-3m15s 甚至 500），**重启 Ollama 才能恢复**（注意：kill server 后孤立的 runner 子进程仍占 VRAM，需一并杀掉）。诊断路径：语音关群聊 24-43s 正常完成（状态机无 Bug）→ Ollama server.log 还原退化时间线 → 显存逐进程排查。
- **测试脚本竞态 Bug（两处，曾致验收 6 假失败 3 项）**：①「✨ 正在回复中」提示气泡同属 `.chat-row.assistant .bubble`，wait_for 的 formal 计数把它误当正式回复提前退出（记录到 user=1/formal=1 的假状态）——修复：计数排除 `.replying` + 条件加 hint==0；②单聊 fragment 仍阻塞在 POST 中时就导航/发送，点击落到旧页面（消息进了单聊 pending、群聊错误未清）——修复：每轮前 wait_idle（replying 消失）+ assert_page（placeholder 校验单聊/群聊页面正确）。
- **Ollama 行为记录**：keep_alive=-1 时 /api/ps 的 expires_at 显示 2319 年；keep_alive=0 卸载；客户端断开会中止加载中的模型（「client connection closed before server finished loading, aborting load」）——**测冷加载时 curl 超时必须设够长（>150s），否则每次都把加载打回重来**。
- **遗留（待用户定夺）**：①前端 120s 超时值未动（用户明确先不改；冷启动 ~137s 场景已被预加载方案覆盖）；②**mika 的 GPT-SoVITS v4 权重与 qwen3:8b 常驻的显存冲突是结构性问题**——语音开+群聊涉及 mika 时 TTS 慢（权重来回切）且可能触发 runner 退化殃及后续所有 LLM 请求；可选方向：mika 语音换 v2 权重（yuuka 的 v2 + qwen3 实测可共存）、或接受语音场景下换更小 LLM、或 TTS 前后编排卸载/重载 LLM（改动超出本轮 TTS 范围限制）。
### 45. mika 语音权重 v4→v2 同步：消除 BigVGAN 显存冲突（2026-10-17）
- **背景**：第 44 条定位的群聊卡死根因——mika 的 SoVITS 权重实为 **v4 LoRA**（文件头 `04`，72MB 增量），虽放在 `SoVITS_weights_v2/` 目录；运行时 api.py 需加载 v4 底模 + BigVGAN vocoder 共 ~4.7GB 显存，与 qwen3:8b 常驻（5.5GB）在 8GB 卡上冲突 → Ollama runner 退化。yuuka 是本地自训的 v2 完整权重（82MB 自包含，~1.7GB 显存）。
- **版本判定方法（GPT_SoVITS/process_ckpt.py）**：新格式训练产物用文件头 2 字节存版本（`04`=v4 LoRA、`01`=v2、`05`=v2Pro），标准 zip pickle（`PK` 开头）才按文件大小判版本；`load_sovits_new` 加载时把头 2 字节还原为 `PK`。
- **mika 无法重训 v2**：`logs/` 下只有 youxiang（CH0184 游戏语音，yuuka 自训数据）和一个中断的 v2Pro 实验 xxx，**mika 无本地训练数据**，其 v4 LoRA 权重来自外部。
- **方案（最小改动：仅改 characters/mika/character.json 一行 + 清 TTS 缓存，零代码改动）**：`sovits_model` 从 v4 LoRA 改为 **v2 官方预训练底模** `GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s2G2333k.pth`（106MB 完整权重）——mika 音色改走 **zero-shot 克隆**（由 reference.wav + prompt_text 提供，GPT-SoVITS 设计内能力）；`gpt_model` 保持 Mika-e10.ckpt 不变（v2 系 GPT，保留 mika 韵律先验）。
- **实测（重启后端+重启 GPT-SoVITS 干净日志验证）**：
  - **版本确认**：连续 4 次合成日志全为「模型版本: v2」，配置生效 ✓
  - mika 首合成（含首次 v2 底模加载）34.6s；连续合成（权重缓存命中）13.0s；yuuka↔mika 切换 52.5s / 47.5s
  - 显存 7761/8188 MiB（v4 时代 mika 单独就吃 ~4.7GB，现回到 v2 量级）
  - **质变**：Ollama 无 500/无 runner 退化（v4 时代会恶化到 1-3 分钟并死锁）
  - 试听样本：cache/mika_v2_a.wav
- **残留（如实汇报）**：v2 下全链耗时仍 13-52s，瓶颈已不在权重加载（v2 秒级）而在 **Ollama 翻译**——qwen3:8b(5.5GB)+GPT-SoVITS v2(~1.7GB)+桌面 共 7.8GB 逼近 8GB 上限，GPT-SoVITS 合成显存峰值期间 Ollama 翻译被挤到共享内存，实测 9.6-42.8s 波动（空闲时 1-3s）。属 8GB 卡上 LLM+TTS 双常驻的固有压力，与 v4 问题无关；缓解方向（翻译换小模型/TTS 翻译改本地词典/接受波动）超出本轮范围。
- **音色验收**：mika 改走 zero-shot 克隆，音色相似度与原 v4 LoRA 微调版可能有差异，待用户试听 cache/mika_v2_a.wav 判断；若不满意，长期方案是用 mika 语音数据（需自备）在 v2Pro 底模上重训完整权重。
### 46. 群聊后发言成员逐字复用前发言成员的建议与理由：任务指令加正向差异化引导（2026-10-17）
- **现象**：群聊中优香与未花回复高度相似——用户问「我刚起床呢，今天周末大家有出去玩吗」，优香「我还在处理一点研讨会的事情，不过可以考虑一下出去玩的建议。水族馆或者附近的商场怎么样？」、未花「我还在处理一点茶会的事情，不过可以考虑一下出去玩的建议。水族馆或者附近的商场怎么样？」——专属名词不同但结构、建议、理由完全一致。
- **根因（实测区分后确认）**：**建议/推荐类问题上的上下文锚定**。分步生成时前面成员的完整回复以 `[名字]：` 行进入后发言者的【群聊记录】末尾（离生成位置最近），而两人的任务指令完全相同、无任何差异化引导——qwen3:8b 把「前成员的完整推荐+理由」直接搬用为自己的答案。实测证据（脚本模拟前端分步调用）：
  - 建议类问题「中午不知道吃什么，你们有什么推荐吗？」修改前 **2/2 轮逐字复用**：优香「咖喱餐厅，分量足而且味道好」→未花「我刚刚和优香聊到附近那家咖喱餐厅，分量足而且味道好」；优香「居酒屋…中午吃点清淡的也挺好」→未花「居酒屋应该不错哦，虽然不是正餐，但中午吃点清淡的也挺好」（稳定复现）。
  - 复现案例（出去玩问题）3 轮仅轻微相似（反问句相同）——该形态与第 39 条记录的「随机收敛」一致，非稳定镜像。
  - 未花单独答（上下文无优香回复）3 轮各自多样（茶会活动/同学野餐/公园走走）→ 锚定源确认为优香回复在上下文，非未花自身先验。
  - `_group_note` 第 4 条既有负向禁令（「不要把对方刚说的观点原样复述成自己的」）对 8B 模型无效——再次印证「负向禁令防不住复制」（见记忆 prompt-negative-reference-reuse-pitfall）。
- **修复（最小改动：仅 `backend/services/llm_service.py` `group_chat_stream` 的 user_content 任务指令一处）**：「征求建议」分支追加**正向**差异化引导——「如果群里已有成员就这个问题给出了具体建议，就提出一个不同的想法，或从你自己的角度给出新的补充」。正向行为指令（要做什么）而非负向禁令（不许复用 X），且放注意力最强的 user 位置（system 远端的群聊记录不展示旧文本、不点名「不要像优香」——避免诱发对照复制）。未改 `_group_note`、未改角色 prompt、未改消息结构/采样参数/单聊/TTS。
- **修改前后对比（同一建议类问题）**：修改前未花两轮均逐字复用优香理由（见上）；修改后两轮——优香「快餐店，不用花太多时间，而且中午人也不算太多」/未花「学校附近那家咖喱餐厅…味道很香，分量也刚刚好，要不要一起去？」；优香「居酒屋…吃点清淡的」/未花「我在茶会的时候看到附近有一家新开的拉面店…要一起去吗？」——推荐、理由、语气全部独立，未花还自然带出茶会语境。
- **验收（qwen3:8b，同组问题重复测试）**：①不总推荐同样活动——复现案例 3 轮未花分别推荐咖啡厅/茶会点心邀请/展览邀请，未再与优香镜像（第 3 轮与优香同提「展览」但为茶会语境的邀请补充，非复述）✓；②不再出现换名词复制结构（修改前 2/2 → 修改后 0 例）✓；③理由偏好体现各自性格（优香实用理性「不用花太多时间/人不多」，未花茶会语境+活泼邀请「在茶会的时候看到…要一起去吗？」）✓；④用户指出「你们俩回答得也太像了吧」时自然回应（优香吐槽式反问「是觉得我们回答太像，还是觉得建议太普通？」、未花俏皮承认并接话，无人设崩坏）✓。
- **遗留观察（不在本轮范围）**：优香 3 轮都推水族馆/展览——其 prompt【语气参考】含「水族馆…特别展」示例（第 42 条遗留观察已记录同根因：优香单聊建议与示例几乎逐字一致），属优香人设先验倾向而非未花模仿；如需提升优香自身建议多样性，可参照未花 prompt 的「不要照抄示例里的句子」说明，待用户定夺。
### 47. 群聊逐字复读复发：三层根因定位 + 生成层复读检测三级重试兜底（2026-10-17）
- **现象（真实对话复现第 46 条修复失效）**：①「你们有没有推荐的地方呢」→优香、未花逐字输出同一句「水族馆怎么样？最近有个特别展，不会太累也能逛得开心。老师想去哪里玩呢？」；②追问「你们怎么推荐一个地方啊，有理由吗」→两人**再次逐字复读同一句**（连问句结尾都相同）。
- **定位方法（用户要求先定位不改码）**：monkeypatch `aiohttp.ClientSession.post` 捕获每次真实发给 Ollama 的 payload，直接调后端同款 `llm_service.group_chat_complete` 复现用户 4 轮真实对话 + 变量分离实验（R1-R5 共 26 次生成）。**排除消息构造 bug**：每次请求的最新用户消息、角色 prompt、历史列表（无重复追加/错误截断）、temp=0.95/top_p=0.9/max_tokens=150 全部正确——是模型行为，非代码 bug。
- **三层根因（全部实验证实）**：
  1. **源头：优香逐字搬用自己 prompt【语气参考】示例**——空历史直接问推荐 2/2 逐字输出「水族馆怎么样？最近有个特别展，不会太累也能逛得开心」（第 42 条遗留观察的群聊版；优香 prompt 缺未花那样的「不要照抄示例句子」说明）。追问时她复读的就是这句。
  2. **中继：未花逐字沿用优香句**——R1 滚动复现 2 次中 1 次逐字抄（连结尾问句都抄）；第 46 条加的正向引导**降频但未根除**（优香的 prompt 原句形似「标准答案」+话题已聚焦时仍锚定）。
  3. **放大器：追问「有理由吗」触发复读自己**——固定真实历史（轮 3 两条逐字相同句）追问后 **6/6 逐字复读**；轮 3 两人回复不同时优香 3/3 能重组给理由、未花 3/3 仍复读自己。**重复出现的相同句子+追问=最强复读触发**，既有负向禁令（「不要重复刚才的话」）完全无效。复读对象实测是「自己的原话」。
  - R5（用户指出两人一模一样）回应正常，无需处理。
- **结论：纯提示词路线证伪**——正向引导只降频不根除、负向禁令无效、优香源头在 prompt（本轮禁改）。转**生成层兜底**（与 `_sanitize_group_reply`「不依赖模型自觉」同思路）。
- **修复（仅 `backend/services/llm_service.py`，单聊/TTS/prompt/成员顺序/fragment 零改动）**：
  - `_norm_text`（归一化去空白标点）+ `_is_echo`（与参照文本逐字相同/互为长子串/相似度≥**0.85** 即复读；实测「删掉开头半句式复读」≈0.87、重组转述正常回应均 <0.75，0.85 恰好分隔）+ `_echo_refs`（参照=自己历史最近一条+其他成员历史最近一条+turn_replies）。
  - `group_chat_complete` 复读检测+**三级重试**：初始生成判复读→重试 1（user 追加正向指令「老师在追问理由就讲出自己的理由…相近意思也必须换说法」，不展示被复读原句全文——负向+展示全文反而诱发复制）→仍复读→重试 2（指令 + 把 speaker 自己最近一条历史行在 transcript 里**替换为占位标注**「这句发言老师已经听到了…老师在等你说新的内容」——防重复靠结构：锚点原文不在上下文里就无从逐字复制；仅本次生成的临时视图，不改真实历史）。每次重试后复检，通过即返回；两次均失败接受最后一次，不无限重试。
- **修改前后对比（同一极端场景：轮 3 两条相同水族馆句+追问「有理由吗」）**：修改前 6/6 逐字复读「水族馆怎么样？…」；修改后优香答「水族馆最近刚好有企鹅和北极动物的特别展览，不会太晒…也可以考虑附近的商场」、未花答「可以去附近的公园，风景不错人也不多」（各自给出真理由/新建议）。
- **回归统计（qwen3:8b 共 62 次生成）**：V1 极端场景 4/4 OK；V2 完整 4 轮滚动 ×3 共 24 次生成 **0 残留逐字复读**（轮 4 追问优香均「重组+理由」、未花触发重试后均给新建议+理由）；检测触发 10 次全部救回（7 次重试 1 通过、3 次顽固 case 走占位替换后通过）；V3 不误拦（重组句/指出一模一样的正常回应均放行）。API 冒烟（含一次性双成员调用）正常。中间版本曾出现「重试后仍复读自己轮 3 原话」残留 2/28 与「删前缀式复读」0.872 漏检，分别以双次重试+占位替换、阈值 0.9→0.85 解决。
- **已知残留与边界（如实汇报）**：①优香轮 3 仍会说「水族馆…特别展」（prompt 示例先验，不在聊天记录里、不构成复读，检测不拦也不该拦）——两人不再一模一样、追问有理由，核心问题解决；优香建议多样性需改其 prompt（第 42 条遗留），待用户定夺。②占位替换只针对「复读自己」路径，「复读他人」顽固 case（实测均一次重试救回）未做占位——如未来复发可扩展。③重试最多 2 次意味着最坏单成员 3 次生成（~20s），群聊串行等待可接受。
### 48. 优香【示例使用规则】prompt 调整：源头治理示例照抄 + 生成层检测保留验证（2026-10-17）
- **背景**：第 47 条定位三层根因后，遗留「优香 prompt 示例照抄」源头待治理（当时禁改角色 prompt）。本次按用户给定文本在 `characters/yuuka/prompt.txt` 末尾【语气参考】之后新增【示例使用规则】章节：语气参考用于理解说话风格而非固定台词/默认推荐答案、应结合当前情境独立组织回答不照搬完整句子/活动推荐/理由、可再次推荐水族馆展览等活动但理由和表达应按当前情境组织、不必刻意避开示例活动也不为差异强行相反。未动其他章节、未改未花 prompt、未改性格设定。
- **生成层保留确认（llm_service.py 零修改）**：第 47 条修复完整成立——`_is_echo` 阈值 0.85 检测、三级重试、第 2 级临时 transcript 视图占位替换（不改真实历史）、重试成功才返回；单聊/群聊成员顺序/点名优先/st.fragment/TTS 均不受影响。
- **回归验证（qwen3:8b 13 次生成 + API 冒烟，5 场景）**：
  - S1 优香独立推荐（空历史）×4：修改前 2/2 逐字照搬完整两句示例（sim=1.0）→ 修改后 **0/4 完整照搬**——商场句 0/4 消失、与完整示例 sim 降至 0.623~0.708，均推荐水族馆并自然追加「老师觉得呢？」等反问。**残留**：首句「水族馆怎么样？最近有个特别展，不会太累也能逛得开心」4/4 保留（模型对该场景的强先验，符合规则「可以再次推荐水族馆」的方向，但表达未完全独立）。
  - S2/S5 群聊建议（优香已回复水族馆，未花跟进）×3：未花 3/3 独立推荐公园（与优香 sim 仅 0.111~0.132），0 照搬、无强行相反意见——正常承接（提出自己的想法）。
  - S3 追问理由（双相同句历史+为什么）×3：修改前 6/6 逐字复读自己 → 修改后 **3/3 针对当前问题给出新理由**（「因为最近水族馆在办一个特别展览，有很多稀有鱼类和互动项目」等，与自己上一条 sim 0.386~0.478），连此前 3/3 复读自己的未花也正常重组。
  - S4 指出相似（你们怎么说一样的话）×3：3/3 自然回应（优香吐槽式带过、未花俏皮承认），无复读、无答非所问。
  - 检测触发 13 次全部 0——prompt 修改后模型行为改善，生成层检测作为兜底未被需要（设计意图：源头治理降低触发率，检测保底）。
- **API 冒烟**：重启后端后 /api/group/chat 双成员调用 status 200、ok=True×2，优香推荐水族馆未照搬完整示例（sim=0.708、无商场句），未花独立推荐咖啡馆。
- **提交说明**：本次提交 characters/yuuka/prompt.txt（示例规则）、backend/services/llm_service.py（第 42/46/47 条群聊功能+复读检测，第 48 条回归的基础，且复读检测依赖同文件群聊代码不可分离）、CHANGELOG.md（第 42~48 条记录）；main.py/tts_service.py/mika 文件/streamlit_app.py/backend/data 等其他功能修改不在本次提交范围。
### 49. 语音突然用不了：TTS 翻译请求漏传 think:false 被 qwen3 思考耗尽 num_predict（2026-10-17）
- **现象**：语音突然用不了——/api/tts-audio 对真实长度文本返回 503「翻译结果为空」（11.6s 后），GPT-SoVITS（9880）在线、/api/tts/status 正常、显存 7.4GB 权重已加载；部分文本（如「测试」「水族馆怎么样？…」）仍 200 成功，时好时坏。
- **定位（实测复现）**：直接复现 Ollama 翻译请求（qwen3:8b，stream=False，num_predict=300）——响应 `message.thinking` 504 字符、**`message.content` 为空**、`done_reason: "length"`。根因：`tts_service.translate`（tts_service.py:77-88）的 payload **漏传 `"think": False`**——qwen3 系列默认思考模式，思考内容把 300 token 限额全部耗尽，正式翻译还没输出就被截断 → content 为空 → 抛「翻译结果为空」→ 503。思考长度概率性波动（temp=0.3）导致时好时坏（「突然」用不了的形态）。聊天请求（llm_service.py 单聊 :225/群聊 :457）均显式 `"think": False` 所以聊天一直正常，唯独翻译请求漏了。
- **修复（最小改动：仅 tts_service.py translate payload 一处）**：加 `"think": False`（与聊天请求一致），qwen3 直接输出翻译不思考——content 永不为空，且翻译更快。未改 num_predict（不思考后一句日语翻译约 30-60 token，300 充足）、未改合成/缓存/权重切换逻辑。
- **验证（重启后端后，qwen3:8b）**：4 条真实长度文本 + 1 条未花音色 **5/5 全部 200**（含修复前失败的「今天天气不错，出去走走吧。」6.5s 成功；「水族馆…」命中缓存 0s；新合成 4.8-5.3s——修复前翻译 9-12s 且部分失败）。
- **遗留观察**：显存 7583/8188 MiB 仍逼近 8GB 上限（qwen3:8b 5.5GB + GPT-SoVITS v2 ~1.7GB + 桌面），TTS 合成 GPU 峰值期间 Ollama 翻译可能被挤到共享内存变慢（第 45 条已记录），属 8GB 卡双常驻固有压力，非本次缺陷。
### 50. 角色系统第一阶段：启用状态独立持久化 + 配置健康检查（2026-10-17）
- **新增 `backend/services/character_state.py`**：启用状态存独立状态文件 `backend/data/character_state.json`（格式 `{"enabled": {"角色id": true/false}}`，与 model_state.json 同目录同风格，不改 character.json/prompt.txt、不改模型状态机制）；只存显式记录，**无记录的角色默认启用**（新角色开箱即用）；`is_enabled`（请求前验证用）/`set_enabled`（持久化并返回诊断）/`diagnose`/`health_report`（纯文件系统+JSON 检查，不调 Ollama 生成、不合成语音）。**状态文件损坏安全处理**：不静默覆盖/重置——先备份原文为带时间戳的 `.corrupt-<时间戳>` 文件（用户数据保留可手工恢复），本次读取安全回退「全默认启用」，损坏详情（JSONDecodeError 等）经 health 的 state_file 字段报告。
- **health_report 三层分开表示**：`discovered`（目录存在）/`loaded`（已加载进内存）/`config_ok`（JSON 解析成功+必需字段 id/name/model 齐全）/`prompt_ok`/`avatar_ok`/`tts_ok`（三态：None 未配置、True 完整、False 异常）/`enabled`/`issues`（逐项中文诊断）。TTS 异常只记录不阻止文字聊天；单个角色损坏只影响自己的诊断条目。修复实施中发现的误报：character.json 里 TTS 路径是相对路径（相对项目根，与 tts_service._resolve_path 同规则），存在性检查按 PROJECT_ROOT 解析后 yuuka/mika tts_ok 恢复 True。
- **character_service.py 最小修改**：`load_all` 记录 `self.discovery`（{目录名: {loaded, error}}）；`_load_one` 配置缺失/损坏时抛异常（FileNotFoundError「缺少 character.json/prompt.txt」）替代 return None——load_all 捕获记录具体原因，外部行为不变（该角色不加载、其他不受影响）；新增 `is_loaded`。
- **main.py 接口变化**：`/api/characters` 响应每角色新增可选字段 `enabled`（兼容，旧前端不受影响）；新增 `GET /api/characters/health`（全角色健康汇总，注册在 {character_id} 路由前避免路径被吞）；新增 `POST /api/characters/{character_id}/enabled`（body `{"enabled": bool}`，返回含 state_file 诊断）；**后端请求前验证**：`/api/chat` 停用角色 403「角色已停用: X」、`/api/group/chat` 停用成员占位「⚠️ X 已停用」ok=False 不进后续上下文不阻断其他成员（与「成员不存在」同模式）、`/api/tts-audio` 停用角色 403。
- **未动**：llm_service.py（生成/复读检测/重试/模型预加载零改动）、tts_service.py、前端（fragment/CSS/布局零改动，启用状态展示留第二阶段角色管理界面）、模型状态 JSON 机制。
- **测试（qwen3:8b 驻留，探针脚本已清理，临时角色目录已删除）**：①yuuka/mika 正常加载 enabled=true ✓；②_test_broken（坏 JSON）不进列表、其他角色正常、health 诊断含 JSONDecodeError 定位 ✓；③_test_noprompt（缺 prompt.txt）诊断「缺少 prompt.txt」✓；④_test_new（完整配置无状态记录）默认启用 ✓；⑤mika 停用跨后端重启保持 ✓；⑥停用拦截：单聊 403、群聊单成员占位 ok=False、混合群聊 yuuka 正常生成+mika 占位不阻断、TTS-audio 403 ✓；⑦状态文件损坏：health.state_file.ok=False+具体错误+备份保留，列表全员默认启用，set_enabled 正常重建 ✓；⑧现有功能：单聊/群聊生成 200、模型预加载 ok、TTS status True ✓；⑨恢复启用后单聊正常 ✓。
- **未验证项**：前端 UI 对停用角色的展示（本阶段未动前端）；`GET /api/characters/health` 在大量角色目录下的性能（当前 2 角色 <50ms）；并发请求下状态文件读写竞态（单人使用低并发，文件小开销可忽略）。
### 51. 角色系统第二阶段：独立角色管理页面（2026-10-18）
- **新增 `frontend/character_admin.py`（独立管理 UI 模块，入口 `render_character_admin_page()`）**：`_fetch_all` 拉取角色列表+健康报告（session_state 缓存 `_admin_cache`，避免每轮 rerender 重复请求）；`_set_enabled` 调 `POST /api/characters/{id}/enabled`，**以服务端返回为准**（失败也重新读服务端状态），配合按钮防重复点击；`_health_summary` 四级摘要（ok/warn/bad/unknown，loaded 与 config_ok 分开——目录在但未加载≠配置坏）；`_render_entry` 角色卡片（头像/名称ID/启用徽章/健康摘要/详情 expander/启停按钮）；页面入口含操作结果消息、手动刷新+时间戳、后端不可达提示「当前显示的可能不是最新数据」、状态文件损坏提示（指向 health 的 state_file 诊断）。坏 JSON 角色不在列表中（后端不加载），通过健康报告的 discovered-not-loaded 条目**动态发现并展示诊断原因**。
- **`backend/main.py` 仅改 health 端点（+10 行）**：`/api/characters/health` 响应过滤绝对路径——state_file 移除 path 键、corrupt_backup 只保留文件名（安全：不暴露本地路径给前端）。services 四文件（llm/tts/character_service/character_state）零修改，第一阶段逻辑未动。
- **`frontend/streamlit_app.py` 最小集成（+13 行）**：import character_admin、main() 路由加 `cid == "charadmin"` 分支、侧边栏底部新增「👤 角色管理」导航按钮（与「返回大厅」同区）、底部版权显示条件排除管理页。只做导航集成，聊天页 fragment/CSS/布局零改动。
- **实施中修复的 bug**：启停按钮初版 `_set_enabled(cid, enabled)` 误传当前状态而非目标状态（enabled=True 时点「停用」实际执行了「启用」）——修正为 `target = not enabled`。Playwright 实测发现（页面提示「已启用」而预期停用），非静态检查可发现。
- **Playwright UI 验收 22/22 全 PASS**：V1 大厅回归（聊天入口/生成正常）；V2 管理页（打开/角色卡片/坏 JSON 角色 _admin_bad 动态发现+「未加载」诊断）；V3 详情 expander 三检查项（启用状态/配置/Prompt）；V4 停用成功；V5 reload 后仍停用（持久化）；V6 重新启用；V7 手动刷新更新时间戳；V8 回大厅；V9 无原始文本污染（字体覆盖不破坏布局）。技术细节：chromium 经本地代理下载（`HTTPS_PROXY=http://127.0.0.1:7897`）；Streamlit 1.63 expander 是无 data-testid 的 `<details>/<summary>`，选择器用 `summary:has-text(...)`；expander 箭头图标（stIconMaterial）因全局字体覆盖被 Streamlit 防污染机制 display:none（🔍 emoji 提供视觉标识，功能正常）。
- **后端不可达场景**：页面显示「无法连接到后端服务」+「当前显示的可能不是最新数据」（读缓存）✓。**回归**：单聊 200（3.1s）、群聊 200、模型预加载 qwen3:8b ok、TTS status True、TTS 合成 200（16.1s）✓。
- **清理**：临时角色 _admin_bad 已删、Playwright 脚本与输出已删、character_state.json 已删（恢复原始状态=文件不存在）。前后端均在运行（8000/8501）。
- **未验证项**：管理页在真实浏览器（非 headless）的视觉效果；多用户并发操作状态文件的竞态（单人低并发，第一阶段已知边界）。
### 52. 角色系统第三阶段：角色配置编辑（名称 / 简介 / 人设 / 头像）（2026-10-18）
- **`backend/services/character_service.py` 新增编辑服务（+175 行，不改加载/发现逻辑）**：`reload_one`（保存后重载单角色内存——llm_service 每次聊天都经 `character_service.get()` 取 prompt，reload 后后续聊天即用新人设，**llm_service.py 零改动**）；`_atomic_write_text`（同目录临时文件 + `os.replace` 原子替换，失败保留原文件，统一 LF）；`update_profile`（名称去首尾空白、禁止为空；从磁盘读当前 json 仅改 name/description 字段，其他字段原样，ensure_ascii=False + indent=2 保持原格式）；`update_prompt`（禁止空提示词，原文写入保留换行与中英日字符，保存后重读校验内容一致才返回）；`update_avatar`（≤5MB、PIL `verify()` 完整解码校验、PNG/JPG/WEBP 白名单——扩展名由图片实际格式决定不信任上传文件名；换格式时旧扩展名头像先改名备份再替换、任一步失败回滚恢复，成功才清备份——否则 `get_avatar_path` 按优先级仍会命中旧文件；写入路径全部由服务端拼接到该角色目录内）。PIL 为函数内 import（环境已随 Streamlit/GPT-SoVITS 提供，不新增依赖声明）。
- **`backend/main.py` 新增 4 路由（+59 行）**：`GET /api/characters/{id}/profile`（编辑页数据：name/description/prompt 全文/avatar_ext）、`PUT .../profile`（名称+简介）、`PUT .../prompt`（人设）、`POST .../avatar`（base64 JSON 上传，避免 multipart 依赖）。错误统一 HTTPException 中文 detail（400 校验 / 404 角色不存在 / 500 写入失败），不暴露绝对路径与堆栈。不存在角色 404、路径穿越 ID 经内存字典查找天然 404、无任何路径参数不受信任。
- **`frontend/character_admin.py` 编辑视图（+269 行）**：卡片「✏️ 编辑配置」按钮（仅 loaded 角色）→ 编辑页分区块保存（头像 / 名称与简介 / 人设提示词），每区独立校验独立保存互不影响；表单初值来自服务端 GET profile，保存后重拉以服务端为准；头像预览与列表头像 URL 加 `?v=<时间戳>` 破浏览器缓存（更换头像后立即可见新图）；退出编辑清全部 widget state（下次进入显示服务端最新值）。
- **实施中修复的 bug**：头像上传成功后 `st.session_state[uploader_key] = None` 清空选择器——在 file_uploader **已渲染后的同一 run 内**赋值会被 Streamlit 拒绝（StreamlitAPIException 中断脚本，上传成功但成功消息与预览刷新全部丢失，后端日志 POST 200 但无后续 GET）。修复：置清空 flag，下次 rerun 在 uploader 渲染**之前**赋值。
- **测试（API 32/32 + 行为验证 + UI 15/15 + 回归 10/10，测试后已全部还原）**：①API：profile 读写与磁盘一致、名称 strip、空名称/空人设/假图片/超 5MB/无效 base64/BMP 白名单外均 400 且原文件不动、jpeg↔png↔jpg 格式切换旧文件清理无 .bak 残留、其他字段（greeting/tts/color/model）不受影响、不存在角色与路径穿越 404、未花不受影响；②聊天新人设生效（行为级验证）：PUT「只回复 P3OK」的测试人设后单聊回复恰为 P3OK，还原后恢复正常优香语气；③UI（Playwright）：编辑入口/初值一致/空值拒绝/名称保存/人设保存/头像上传+预览刷新（?v 变化）/列表新名称/未花不受影响/重进编辑页显示保存后值；④回归：健康检查（state_file 无 path 键）、启停（停用→群聊占位「⚠️ 圣园未花 已停用」不阻断→恢复）、单聊 200、群聊双成员 ok、TTS tts_available=True + 合成 200、模型 qwen3:8b。测试中的 2 个脚本级误报（T2d 断言把「老师」写成「先生」、UI 测试在清空后才取人设基线导致服务端被写短）均已定位为测试自身问题并修正，非产品缺陷。
- **范围控制**：未创建/删除角色、未动模型/TTS 参数、llm_service.py 与 tts_service.py 零改动、聊天页 fragment/CSS/群聊/单聊/启停/健康检查语义不变、无新依赖（PIL 复用环境既有）。简介沿用 character.json 既有 description 字段。
- **清理**：测试备份与脚本（cache/p3test/）已删、优香配置三件套已字节级还原（json/prompt 与原件 diff 为空、avatar.jpeg 恢复、测试 png/jpg 已删）、character_state.json 已删（回归测试产生，原始状态=不存在）。
- **未验证项**：编辑页在真实浏览器（非 headless）的视觉效果；上传超大分辨率图片（仅校验了字节数与可解码性，未限制像素尺寸）；多用户同时编辑同一角色（单人低并发场景）。
### 53. 头像像素尺寸安全检查补充（2026-10-18）
- **背景**：第 52 条遗留「未限制像素尺寸」——超大分辨率图片虽受 5MB 字节数与可解码性校验，但缺像素级限制（解压炸弹类风险：小文件声明超大尺寸）。
- **修改（仅 `backend/services/character_service.py` 的 `update_avatar`）**：新增常量 `MAX_AVATAR_EDGE=4096`（最长边）与 `MAX_AVATAR_PIXELS=16_000_000`（总像素 1600 万）；`Image.open` 后**解码前**按 header 中的 `img.size` 检查（此时像素未加载，拒绝超大图不耗解码内存），超限 400「图片尺寸过大（W×H，要求…）」；用 `warnings.catch_warnings()` + `simplefilter("error", Image.DecompressionBombWarning)` 包住 open+verify——PIL 的 DecompressionBombWarning 升级为异常、DecompressionBombError 本身是异常，两者统一捕获后 400「图片像素数过大（疑似解压炸弹），已拒绝」（与「无法解码」区分错误信息）。所有校验仍在写入之前，拒绝时原头像不动（既有原子写/回滚机制不变）。
- **测试（10/10 PASS，测后已还原）**：①最长边 4097×100 → 400 尺寸过大；②边合规但总像素 4096×4096=1677 万超限 → 400；③手写假 PNG（IHDR 声明 100000×100000、IDAT 仅一行数据，落 PIL 炸弹区间）→ 400「疑似解压炸弹」——错误信息证实 PIL 的 DecompressionBombError 分支真实触发（非仅靠自身尺寸检查）；④三次拒绝后原头像 sha256 逐字节一致、无 .bak/.tmp-write 残留；⑤合法 512×512 上传 200（磁盘切到 avatar.png）；⑥边界值 4000×4000（=1600 万整，不超）上传 200；⑦回归：假图片/超 5MB 既有校验仍 400。还原：avatar.jpeg 从 git 恢复（130990 字节）、avatar.png 已删、重启后端确认 avatar_ext=jpeg 且头像接口字节与磁盘一致、健康检查两角色 loaded+config_ok、单聊 200（5.8s）。
- **范围控制**：main.py 路由/前端 character_admin.py/llm/tts/群聊/预加载零改动；无新依赖（warnings 为标准库）。
### 54. 更换头像抛 StreamlitValueAssignmentNotAllowedError：file_uploader 清空只能换 key（2026-10-18）
- **现象（用户真实使用复现）**：给 mika 更换头像后抛 `StreamlitValueAssignmentNotAllowedError: Values for the widget with key '_eavatar_mika' cannot be set using st.session_state`，堆栈落在 `st.file_uploader` 渲染处——脚本中断，成功消息与头像预览之后的区块（名称/人设）全部不渲染。
- **根因（两层）**：第 52 条的「渲染前赋值」修复对 Streamlit 1.63 无效——uploader 在之前任何 run 实例化过后，对该 widget key 的**任何用户代码赋值**（无论渲染前后）都会在渲染时被 `check_session_state_rules` 拒绝（is_new_widget=False + 值来自当前 run 用户赋值）。且第 52 条 Playwright 测试 U7 属**假通过**：成功消息与预览图都在崩溃点**之前**渲染，两个断言恰好都满足，而测试没检查崩溃点之后的区块，脚本实际已崩。后续尝试 pop 只清后端 session_state 副本，file_uploader 的已选文件存于**前端 widget state**，rerun 时前端仍回传旧值，页面上照样显示已选文件。
- **修复（仅 `frontend/character_admin.py`，后端零改动）**：uploader key 改为带序号 `_eavatar_{cid}_{n}`（n 存非 widget key `_eupcnt_{cid}`，其余 rerun 不变保证 key 稳定）；上传成功后序号 +1 → 旧 widget 整体废弃、新 key uploader 为全新空状态——这是 file_uploader 唯一可靠的清空方式；顺手 pop 旧 key 遗留值；`_leave_edit` 相应改为按 `_eavatar_{cid}_` 前缀清理全部序号 key + `_eupcnt_`；删除失效的 `_eclr_` flag 机制。
- **测试（15/15 PASS，复现用户场景：mika 连续两次上传，测后已还原）**：每轮断言六项——成功消息、**无 stException/stError 异常元素**、崩溃点之后区块仍渲染（名称输入框初值正确）、人设 textarea 完整、**uploader 已清空（页面无已选文件名）**、预览 `?v` 刷新；另测退出重进后无残留文件名、无异常、初值正确。前端日志全程 0 Traceback。还原：mika/avatar.jpg 从 git 恢复（36535 字节）、测试 png 已删、后端已重启（avatar_ext=jpg、头像接口字节与磁盘一致、健康检查两角色正常）。
- **教训（测试方法论）**：验证「操作后页面正常」必须断言**崩溃点之后**的元素存在 + 无异常元素标记，只断言操作结果元素（消息/预览）会漏掉脚本中途崩溃的假通过；Streamlit widget key 赋值限制：实例化后赋值必炸、pop 合法但清不掉前端 widget state、file_uploader 清空唯一解是换 key。
### 55. 换头像后侧边栏/聊天页头像不更新：头像 URL 加 mtime 版本破缓存（2026-10-18）
- **现象（用户真实使用复现）**：管理页上传头像成功（编辑页 `?v=` 机制生效、预览正常），但**左侧角色列表头像无变化，刷新也没用**。
- **根因**：第三阶段只给管理页（character_admin.py）的头像 URL 加了 `?v=` 破缓存，而 streamlit_app.py 的 6 处头像引用（侧边栏选中角色 img / 侧边栏非选中按钮 CSS background-image / 聊天气泡 / 大厅 hero 兜底 / 聊天页立绘舞台兜底）全是不带参数的裸 `/api/characters/{id}/avatar`——FileResponse 无 Cache-Control 头时浏览器用 heuristic 缓存旧图，Streamlit rerun 不重建同 src 的 img/CSS（URL 不变不重新加载），页面内「刷新」只触发 rerun 拿不到新图。
- **修复（三处配合）**：①`character_service.py` 的 `to_public_dict` 新增 `avatar_ver` 字段（=头像文件 mtime 秒，实时查磁盘、无头像 None）——换头像后 mtime 变即得新版本值；②`main.py` avatar 端点 FileResponse 加 `Cache-Control: no-cache`（浏览器可缓存但展示前须重新验证，FileResponse 自带 ETag/Last-Modified、未变 304 几乎零开销）——根治 heuristic 缓存，兜底覆盖拿不到 ver 的引用；③`streamlit_app.py` 新增 `avatar_url(cid, ver)` 工具函数，6 处引用改为拼 `?v={avatar_ver}`（侧边栏两处/聊天气泡两处/大厅 hero/立绘舞台兜底 + render_stage_and_background 加 ver 参数）；④`character_admin.py` 换头像成功后清 `st.session_state.characters_cache`（streamlit_app 的角色列表缓存填后不失效）——rerun 后侧边栏重新 fetch 拿新 ver，**换头像后侧边栏立即刷新、无需 F5**。
- **测试（Playwright 6/6 PASS，复现用户场景，测后已还原用户头像）**：上传前侧边栏按钮 background-image 带 `?v=` → 上传新图后同一 rerun 内 `?v=` 变化（1792317994→1792318032）→ 拦截到的 mika 头像响应字节==测试图（浏览器真实加载了新图）→ 回列表侧边栏保持新版本 → 进聊天页选中态 img 同为新 `?v=` → 全程无 stException。后端验证：`/api/characters` 每角色返回 avatar_ver、avatar 响应含 Cache-Control: no-cache + ETag + Last-Modified。回归：单聊 200（mika 15.2s）、健康检查两角色 loaded+config_ok、TTS 在线。
- **注意**：测试期间发现磁盘上 mika/avatar.png（485KB）为用户 17:58 上传的新头像——测试前后均按字节保留/恢复（sha256 校验一致），未被测试覆盖丢失。
### 56. 停用角色聊天报错不友好：HTTP 403 特判为中文提示（2026-10-18）
- **现象（用户真实使用报告）**：停用角色后在聊天页发消息，界面显示「服务错误（HTTP 403）」，不知何意、也无下一步指引。
- **根因**：后端 `/api/chat` 的停用拦截（第一阶段语义，返回 `HTTPException(403, detail="角色已停用: {角色名}")`）本身正常；前端 `send_chat_message` 对所有非 200 统一输出 `服务错误（HTTP {状态码}）`，未区分 403 语义。
- **修复（仅 `frontend/streamlit_app.py` 的 `send_chat_message`，后端零改动）**：在 200 早返回之后、通用错误文案之前插入 403 特判，返回「该角色已停用，如需启用请前往设置中启用」（用户指定文案）。错误仍走既有 `_send_error_` 机制：红色气泡仅 UI 展示、不写入聊天历史、下次发送自动清除；用户消息本身保留在会话中。
- **测试（UI 4/4 + 回归 5/5，未改动任何角色状态）**：mika 当时正处于用户设置的停用状态，测试直接复现真实场景、无需启停切换（测后仍保持用户原样）。①停用角色发消息：新文案正常显示、旧「服务错误（HTTP 403）」不再出现、用户消息保留、无 Streamlit 异常（Playwright 4/4）；②API 层确认 403 + detail「角色已停用: 圣园未花」；③回归：启用角色（优香）正常发送 200、回复写入历史、无错误气泡、无误显示停用文案、无异常（5/5，测试会话关闭即消失、不污染用户对话数据，语音已关避免 TTS 权重切换）。
- **说明**：文案按用户原话执行；实际启用入口在侧边栏「角色管理」页（非「设置」页），如需文案与入口一致可后续调整。群聊停用成员走「⚠️ 已停用」占位不阻断（不涉及此文案）；单聊 403 被拦后无回复产生，连带 TTS 也不会触发（`/api/tts-audio` 的 403 在聊天场景不可达）。
- **范围控制**：后端 main.py / 启停语义 / fragment 结构 / 群聊逻辑 / llm / tts 零改动；仅前端一处分支插入。
### 57. 停用角色的「在线」状态改为「离线」灰显（2026-10-18）
- **需求（用户提出）**：角色停用后，界面上仍显示「在线」（绿点），与实际停用状态矛盾——应显示「离线」。
- **修改（仅前端两文件，后端零改动；enabled 字段 /api/characters 第一阶段已返回）**：
  ①`streamlit_app.py` 四处显示点按 enabled（`char.get("enabled", True)`，字段缺失时保持「在线」不破坏旧语义）——侧边栏选中角色行（HTML）、侧边栏非选中按钮（CSS ::after 的 content 与颜色）、聊天大厅 hero 标签、聊天页角色信息条（`{subtitle} · 在线/离线`）与立绘舞台左下角状态角标（`render_stage_and_background` 加 `enabled=True` 参数，群聊调用不传默认在线、群聊语义不动）；停用时统一灰点灰字（#B3A8BA，与侧边栏次级文字同色），新增 `.off` 变体 CSS（`.sb-status.off .dot` / `.character-status.off .dot` / `.hall-online.off`）。群聊信息条「群聊 · N 人在线」不涉及（表述的是群聊会话而非角色启停）。
  ②`character_admin.py` 启停按钮回调补 `st.session_state.characters_cache = None`（与第 55 条换头像同款）——侧边栏/大厅/聊天页的 enabled 来自该缓存，不清则启停后各页面状态文案不刷新。
- **实施中修复的 bug**：hero 与舞台角标两行插值字符串漏写 f 前缀，`{...}` 被原样输出成字面类名（文案「离线」正确但 CSS 类失效、灰点不生效）——py_compile 不查字符串内容，靠 Playwright 找不到 `.hall-online` 元素暴露。教训：f-string 条件插值改 class 时，逐行核对 f 前缀。
- **测试（21/21 PASS，全程未改角色启停状态：mika 用户所设停用、yuuka 启用，恰好覆盖两分支）**：①静态显示 14/14——大厅 hero「离线」+灰样式、侧边栏未花按钮 ::after「● 离线」灰色（computed style 验证）、进聊天页后选中行/信息条「三一综合学园茶话会会长 · 离线」/舞台角标均「离线」+灰点、yuuka 全链路仍「在线」绿点、无 Streamlit 异常；②启停即时刷新 7/7——管理页停用 yuuka → 侧边栏同 rerun 即变「● 离线」（缓存清理生效）、mika 不受影响、再启用即恢复「● 在线」；测后 state 文件已恢复原样（仅 mika: false，测试产生的 yuuka: true 记录已删——语义等价但保持用户原始状态）。
- **范围控制**：后端/启停语义/403 拦截/fragment 结构/群聊语义/llm/tts 零改动；CSS 仅新增三条灰点变体规则不动既有布局。
### 58. 切换角色时角色信息卡 / 😀 表情按钮闪烁根除：render_app 大 fragment（2026-10-18）
- **现象（用户报告，多年遗留）**：切换角色时两处闪烁——角色信息卡片（名字/身份/在线 + 日历♡语音按钮的白色半透明卡）与 😀 表情展开按钮。
- **根因（第 14 条结论的遗留场景）**：第 14 条已定位闪烁根因＝**full-app rerun**（整页重跑时带白色背景的元素被 React 卸载重建/重绘露白，CSS 方向全部无效），并用 @st.fragment 隔离了聊天交互区（第 16 条又隔离了侧边栏展开/收起）。但**侧边栏的角色切换等页面跳转按钮当时保留 `st.rerun()` 整页重跑**（「切页本就需要整页重跑」）——切页场景的闪烁一直未处理，即本次用户所见。
- **方案（沿用第 14/16 条 fragment 方法，把切页也收进 fragment rerun）**：
  ①新增 `@st.fragment def render_app()` 包住「侧边栏 + 页面路由 + 底部版权」（main() 只保留 set_page_config / init_session_state / 全局 CSS / render_app()）；
  ②`render_sidebar` 去掉自己的 `@st.fragment`（并入 render_app，否则侧边栏交互只重跑内层、主区不更新）；`render_hall_carousel` 同样去掉（嵌套 fragment 内的交互无法触发外层，「开始聊天」切不了页）；
  ③全部导航按钮（侧边栏角色/群聊/管理/设置/返回主页、角色分组展开收起、大厅「开始聊天」「重新加载」、聊天页「返回主页」）由「点击处理 + `st.rerun()`」改为 **on_click 回调改 session_state**（回调先于脚本执行，widget 交互只触发 render_app 的 fragment rerun，React 原位更新子树不闪）；新增 5 个模块级回调（`_nav_to_character/_nav_to_group/_nav_to_page/_reload_characters/_toggle_sidebar_section`）；
  ④`render_chat_fragment` 保留 `@st.fragment` 成为嵌套内层——聊天交互（发送/emoji）仍只重跑聊天区，立绘/信息条不动（第 14 条行为不变）；其内 3 处 `st.rerun(scope="fragment")` 语义不变；
  ⑤character_admin.py 零改动：其内部既有的 `st.rerun()`（app 作用域整页）仍正常（管理页无闪烁元素），且已用临时计数器实测整页 rerun 后 render_app 正常工作。
- **前置实验（决定方案可行性）**：8502 端口隔离验证 Streamlit 1.63 嵌套 fragment——外层 fragment rerun 时内层随之重执行（runs 1→2）、内层交互只重跑内层（2→3）、无异常。结论：嵌套合法，「外层 rerun 更新全页、内层 rerun 隔离聊天区」的双层结构可行。
- **验证（决定性 18/18 + 功能回归 7/7，测后临时计数器已移除、前端已重启）**：①用第 16 条的整页 rerun 计数器（main 主体注入 `#dbg-runs`，fragment rerun 不执行 main 故不 +1）实测七个场景——开始聊天 / 侧边栏切角色（未花↔优香）/ 切回 / emoji 开合 / 进群聊 / 进设置 / 返回主页 / 分组收起——**全程 data-n=1（零整页 rerun）**，且两次角色切换后 `.character-info` 节点身份保持（JS 引用相等 + isConnected，React 复用非重建）；②功能回归：嵌套 fragment 下真实发送回复正常、往返切换聊天历史保留、管理页打开 + 「🔄 刷新」（app-scope 整页 rerun 路径）正常、整页 rerun 后返回主页正常、无 pageerror / 无 stException。
- **未验证项（环境限制，既有结论）**：Playwright 软件渲染抓不到视觉闪烁（第 14 条时期已证），机制层已用「零整页 rerun + 节点身份保持」决定性证明，最终视觉效果待用户真实浏览器肉眼确认。
### 59. 切角色闪烁真凶定位与根除：聊天输入区 widget key 稳定化（2026-10-18）
- **现象（用户复测第 58 条后报告仍未解决）**：侧边栏切换角色时主区两处闪（角色信息卡 + 😀 表情按钮区域）；侧边栏本身无闪烁。
- **DOM 级诊断（节点身份追踪 + MutationObserver + transition 事件，Playwright）**：第 58 条 render_app 大 fragment 后整页 rerun 已消除（上轮 data-n=1 验证），但切角色瞬间仍有一批元素被**卸载重建**：MutationObserver 捕获 3 对 DEL/ADD——`chat_input_{key_base}`（输入框容器）、`send_{key_base}`（发送按钮）、`voice_toggle_{key_base}`（隐藏语音按钮）——**根因：聊天 fragment 输入区三个 widget 的 key 都含 key_base（角色/群 id），切角色即 key 变化，Streamlit 视为不同 widget 整体重建**；且 `stElementContainer` computed `transition: all` 使新挂载容器播放 opacity 0→1 渐入（实测 3 次 `transitionrun prop=opacity`）——输入区整排「消失→重挂→淡入」＝闪。信息卡/立绘/背景/日历/语音 iframe 节点全部身份保持（iframe 因 srcdoc 不随角色变化被 React 复用）。
- **修复（`frontend/streamlit_app.py`，治本＝让切角色时 key 不变）**：①输入区 key 稳定化——`chat_input_{key_base}`→`"chat_input"`、`send_{key_base}`→`"send_msg"`、`voice_toggle_{key_base}`→`"voice_toggle"`（emoji 面板按钮 key `emoji_{input_key}_{i}` 随固定 input_key 自动稳定；`_prepare_send` 内 input_key 同步固定；同一时刻只渲染一个聊天 fragment 故无 key 冲突）；②CSS 与 voice iframe JS 两处选择器 `[class*="st-key-voice_toggle_"]` 去尾下划线（固定 key 后类名为 `st-key-voice_toggle`）；③全局 CSS `[data-testid="stElementContainer"] { transition: height .3s ease, width .3s ease !important }`——排除 opacity 挂载淡入（保险），保留尺寸过渡。
- **副作用（可接受，视为特性）**：输入草稿跨角色/群聊保留（固定 key 共享 value）——切角色不再清空打到一半的字。
- **验证**：①诊断复测：13 项关键元素节点身份**全部 KEEP**（信息卡及子元素/两 iframe/输入框/😀 popover 按钮/发送按钮/立绘/背景/舞台），主区 **Mutation 零增删**、**零 opacity 过渡**——切角色时 DOM 完全无卸载/挂载（注：首轮诊断 popoverBtn 误报 REBUILD 系检测假象——popover 按钮 textContent 实为 "😀expand_more"（含 Material 图标字），纯 '😀' 匹配前后皆 null 判 false；用 includes('😀') 复测 same=True）；②功能回归 12/12：草稿跨角色保留、emoji 追加、语音开关（iframe 内 #voice-btn）、真实发送 200、发送后清空、往返切换历史保留、群聊（共享 key 无冲突）、管理页/主页、无异常。
- **过程中发现的既有 bug（未修，记录待办）**：text_input 有焦点时首次点击侧边栏导航会丢失（fill/输入后直接点角色按钮不切换，先点空白处 blur 或二次点击则正常）——事件流实测 mousedown→blur→focus→mouseup→click 均正常派发到按钮，判定为 blur 值提交触发的 fragment rerun 与 click interaction 的竞争；git stash 回 f2ad982 旧代码复现同样失败＝**第 51 条时期即存在**，非本轮引入，不在本轮修（涉及 Streamlit 1.63 interaction 队列机制，需专项研究）。
- **未验证项（环境限制，既有结论）**：Playwright 软件渲染抓不到 GPU 合成层的视觉闪（第 14 条时期已证），本轮以「切角色零 DOM 重建 + 零挂载动画」为机制层决定性证明，最终视觉效果待用户真实浏览器确认。
### 60. 点表情时聊天区整体闪烁根除：emoji 面板纯 HTML iframe 化（2026-10-18）
- **现象（用户复测第 59 条后报告，且"更糟糕"）**：将表情输入到聊天框时，双方头像、聊天框、输入文本框、发送按钮**均会闪烁**。
- **诊断方法论突破（本轮核心）**：软件渲染 Playwright 的 DOM/Mutation/LCP/transition 四件套在该场景**全部干净**（零图片重载、零布局位移、mutation 仅属性级）——闪发生在 **GPU 合成层**（软件渲染抓不到，第 14/59 条"未验证项"的同源限制）。改用**真实 Chrome（CDP attach）+ Page.startScreencast 捕帧 + 相邻帧像素差分析**直接看见：点表情后有一帧聊天区内容整体"变淡消失"（输入区近白占比 69.6%→59.9%，深色不变＝原位渲染层内容缺失，非露白非位移）。
- **根因**：emoji 面板是 st.popover 内 **40 个 st.button**。每次 fragment rerun（点 emoji 的 on_click 回调触发）时它们的 ElementContainer 批量属性更新（单次点击实测 ~105 次 mutation，其中 80 次属性风暴）→ Chrome 样式重算+重绘风暴 → 合成器在重绘完成前推了一帧空内容＝闪。
- **修复（`frontend/streamlit_app.py`，_render_emoji_panel 重写 + 删除 _append_emoji）**：emoji 网格改为 **components.html 纯 HTML iframe**（项目既有 cal/voice 零 rerun iframe 模式）：rerun 时 srcdoc 不变被 React 复用（零属性风暴，实测属性变化从 105 次降至 3 次）；点击由 iframe 内 JS 处理——用**父窗口原型**的 value setter 改输入框值（`PV.Object.getOwnPropertyDescriptor(PV.HTMLInputElement.prototype,'value').set`）+ dispatch 父窗口 Event('input')（更新 React state，输入框立即显示）+ `el.focus(); el.blur()`（提升 Streamlit 前端 committedValue）。
- **Streamlit 1.63 TextInput 双值模型（重要机制发现）**：input 事件只更新 React inputValue（显示层）；Enter/blur 只提升**本地** committedValue；**值在下一次 interaction（如点发送按钮）触发 rerun 时才随 widget states 快照发给服务器**。三个验证陷阱（均实测踩坑）：①reload 后查输入框值永远为空（值从未单独发送）——必须点发送看消息内容才是正确验证法；②iframe 内 dispatch Enter 无效（推测跨 realm 合成事件未触发 Streamlit 的 keydown 提交路径），focus+blur 有效；③软件渲染与真实 Chrome 行为一致，差异在渲染层不在事件层。
- **验证**：①GPU 帧差复测：表情点击场景帧差全部 <0.1%（修复前整聊天区 2.7-2.8% 缺内容帧两帧）——闪烁根除；②功能回归 13/13：emoji 叠加注入（😀🙃）、消息发送进历史、输入框清空、回复生成、群聊 emoji 面板、切角色、管理页/设置页/主页无异常。
- **附带收益**：emoji 点击后 popover 不再需要服务器回调——popover 保持打开可连点多个表情（体验提升）。
### 61. 切角色空白帧缩短：立绘/背景 base64 改后端 URL + preload 预取（2026-10-18）
- **现象（用户复测第 59 条报告）**：切换角色时整个页面闪。
- **GPU 帧差定位**：切角色呈「旧立绘消失(6%) → 空白静止 2-3 帧 → 新立绘两帧渐显(11%+10%)」模式。根因＝立绘/背景以 base64 data URI 内嵌 st.markdown HTML（mika.png 1.6MB→base64 约 2.2MB），每次 render_app fragment rerun 时 React innerHTML 大替换+解析阻塞主线程，期间合成器无新帧（空白期），新立绘 base64 重新解码渐显。
- **修复（后端 main.py + 前端 streamlit_app.py）**：
  ①后端新增 `GET /api/assets/{subdir}/{filename}`（character/background 两个白名单子目录，文件名正则白名单+resolve 防路径穿越，FileResponse + no-cache 协商缓存，同 avatar 端点模式）；
  ②前端 `get_character_portrait`/`get_background` 改返回 URL（本地 exists 检测保留用于回退逻辑，HTML 从 2.2MB 缩到几十字节）；主页 Hero CSS background 一并受益；
  ③聊天页/主页注入 `<link rel="preload" as="image">` 预取所有角色立绘+背景（进任一页面后其他角色立绘已进 HTTP 缓存，切角色零网络等待；URL 固定无版本号，React 对相同 HTML 复用零开销）。
- **安全验证**：路径穿越 `../main.py` → 404；非白名单子目录 → 404；正常文件 → 200。
- **验证**：①GPU 帧差复测：空白期 3 帧→2 帧，新立绘**两帧渐显变一帧到位**(22%)；②功能回归 13/13（同第 60 条回归套件）：主页 Hero URL 引用、聊天页立绘/背景加载完成、preload 注入、日历/语音 iframe 在位、emoji 面板+发送、切角色节点身份保持（stage/背景/两 iframe 全 KEEP）、mika 立绘 URL 切换、群聊/管理页/设置页/主页无异常。
- **范围控制**：emoji 面板/输入区/fragment 架构/群聊逻辑/llm/tts 零改动；立绘与背景文件位置不动（仍在 frontend/assets/）。
- **遗留（可接受）**：切角色仍有 2 帧空白（~32ms，React reconcile 主线程阻塞，非图片加载）——从"闪烁感"降为"切换感"；若用户复测仍觉闪，下一步方向为 React 分批 commit 深挖或 CSS 淡入过渡。
### 62. 全页闪烁真凶根除：恢复 Streamlit 防闪 opacity 过渡 + 双发守卫 + assets 304（2026-10-18）
- **现象（用户复测第 61 条后仍闪，提供 1920×1080/20fps/27s 真实录屏铁证）**：点表情、切角色均整页闪。录屏逐帧分析（541 帧）：0.8-4.0s 有 8 次全屏级变化（38-42% 像素，单帧亮度 190→221、近白 29%→46%＝露白）；4.8-9.0s 有 9 次右栏 8.3% 变化（消息区亮度 216→194＝内容缺失变暗）。
- **真凶（第 59 条自己引入的 CSS 回归）**：Streamlit rerun 时给运行中的 ElementContainer 切换 emotion 类（`1vo6xi6`↔`gmdcco`，后者含 `opacity:0.33; transition: opacity 1s ease-in 0.5s`）。**0.5s 延迟过渡是 Streamlit 的防闪机制**——短 rerun（<0.5s）在过渡启动前结束，opacity 视觉不变。第 59 条写的 `transition: height .3s, width .3s !important` 覆盖掉了 opacity 过渡 → rerun 期间 class 切到 0.33 立即生效、结束瞬回 1.0 ＝ 每次 rerun 全页「瞬间变淡→恢复」。表情注入（fragment rerun）与切角色（render_app rerun）全部中招。
- **修复（`frontend/streamlit_app.py` ~line 1463）**：stElementContainer 过渡规则改回 `transition: height 0.3s ease, width 0.3s ease, opacity 1s ease-in 0.5s !important`——显式保留 Streamlit 的 opacity 防闪过渡（教训：勿删框架自带的防闪机制）。
- **GPU 验证（真实 Chrome + CDP screencast 帧差 + 亮度分类）**：表情场景 3 连点注入帧差全部 <0.1%（修复前 2.7-2.8% 缺内容帧）；切角色为**单一原子帧切换**（22.5% 一帧到位，无中间帧）；亮度序列每帧均处于合法页面态（优香 179.5 / 弹层 184-185 / 未花 191.1），**无任何变暗、露白、混合中间帧**。
- **诊断过程中的两个重要方法论发现（测试环境伪影，记录防再踩）**：
  ①**窗口遮挡伪影**：Chrome 窗口被遮挡时合成器暂停出帧，screencast 只在输入事件后补帧且内容滞后 1 个交互周期——曾误判为「DOM 已切换但画面滞留 3.5s」。测试须 `--disable-backgrounding-occluded-windows` + `bring_to_front` + rAF 心跳监控；
  ②**图片解码假设否定法**：mika.png 2.2MB 冷解码仅 83.7ms、缓存后 0.3ms——解码不是切换延迟因素，勿凭直觉归因。
- **顺带修复 A（数据完整性，`frontend/streamlit_app.py` _prepare_send）**：发完消息后快速连续切换导航时，Streamlit 对排队 widget 事件的重放会让 send 按钮 on_click 带着旧输入值（鬼影文本）二次触发 → **同一条消息重复发送+重复生成回复**（实测切回原角色后 POST /api/chat 多一次）。守卫：5 秒内完全相同文本视为重放丢弃（真实用户重发同一句至少要等 LLM 回复完成，远超 5 秒，无误伤）。验证：发消息后极速(0.3s)+中速(2.5s)连切共 10 次，POST 零新增、消息行数稳定。
- **顺带修复 B（性能，`backend/main.py` avatar + assets 端点）**：FileResponse 只发 ETag **不处理 If-None-Match**（Starlette 无 304 判定），no-cache 下浏览器每次 rerun 整图重拉（实测每次 rerun mika.png 1.6MB 等全量 200，be.log 刷屏）。显式比对 etag（mtime_ns+size）命中回 304 空体。验证：curl 协商 304 生效；二次进入页面 assets 请求 200=5 冻结、304 递增。
- **功能回归 11/11**：emoji 注入+发送回复、语音开关（iframe #voice-btn 🔊→🔇→🔊）、群聊、管理页、设置页、主页、切角色历史保留、全程无 stException。
- **遗留（低优先）**：聊天 fragment 内 `/api/tts/status` 探测（timeout=3，5s 缓存）在 TTS 合成期间可能给导航 rerun 增加最长 3s 延迟（GIL 竞争）；输入框有焦点时首击导航丢失（第 51 条起既有，未修）。
### 63. 角色创建与删除上线：服务端独立校验 + 安全删除 + in-flight 拦截（2026-10-19）
- **功能（第四阶段）**：管理页「➕ 创建角色」（ID/名称/简介/人设提示词/可选头像）+ 每角色「🗑 删除」（checkbox 二次确认，显示名称与 ID）。
- **新增 API（backend/main.py）**：`POST /api/characters`（创建，头像可选 base64，失败回滚本次目录）；`DELETE /api/characters/{id}`（删除，in-flight 使用中 409 拒绝）。`chat_inflight` 计数器：chat/group/tts 请求开始 +1 结束 finally -1（asyncio 单线程内同步增减无竞态），删除前检查拦截正在被聊天流程使用的角色（实测 409 生效）。限制：/ws/chat 不计数（前端未用该端点）。
- **服务层（character_service.py）**：`create_character`——ID 白名单正则 `^[A-Za-z0-9_-]{1,32}$`（天然拒绝路径穿越）、空名称/空提示词/重复 ID/已存在目录全 400 拒绝、目录双保险校验落 characters/ 直接子目录、失败 rmtree 本次目录；`write_new_avatar`（校验与更换头像共用新抽出的 `_validate_image`，行为不变）；`delete_character`——先 rename 到 `characters/.deleting-*` 隐藏目录（原子，后续任何失败目录都不在原地）→ 清内存 `_characters`+`discovery` → rmtree（失败返回 cleanup_warning，角色已一致消失）。`character_state.py` 新增 `remove_record`（删启停记录防残留）；`load_all`/`health_report` 跳过 `.` 开头隐藏目录（`.deleting-*` 不参与扫描，必要最小修改）。
- **character.json 沿用现有字段结构**：id/name/description/model=qwen2.5:7b-instruct-q4_K_M/temperature/top_p/max_tokens/color/greeting，不写 tts（可选配置，未配置健康检查 tts_ok=None 不算异常）；无头像时 `avatar_ext=None` 走前端既有 👤 兜底，不复制其他角色文件。
- **前端（character_admin.py）**：创建视图（_CREATE_KEY 切换，表单初值只设一次防 widget key 赋值炸，失败换 uploader key 清选择）；删除二次确认（_DEL_KEY per 卡片内展开，checkbox 勾选才可确认）；删除成功后清 admin 缓存 + `characters_cache` + 该角色 `conversations` 历史 + 路由重置（若当前正在该角色聊天页）。
- **测试 47/47 通过**（接口级）：创建（合法/重复 ID/8 种非法 ID 含空格中文斜杠点开头超长/空名称/空提示词/已存在目录不覆盖内容未动/路径穿越未写出/新角色健康检查+真实单聊成功/无头像兜底/坏 base64 回滚）；in-flight（聊天进行中 DELETE 409）；删除（成功后目录/列表/健康/状态记录全清、404、穿越拒绝、优香未花目录与状态不受影响）；回归（优香未花在列、健康全绿、TTS 状态、模型预加载、优香单聊、群聊双回复、启停正常）。`git diff --check` 干净，测试脚本与辅助目录已清理。
### 64. 创建角色补立绘/背景三选一：立绘留空不指向其他角色（2026-10-19）
- **需求（用户验收第 63 条后提出）**：①确认立绘与头像非同一文件（头像在 characters/{id}/avatar.{ext} 经 /api/characters/{id}/avatar，立绘在 frontend/assets/character/{id}.{ext} 经 /api/assets/character/{name}）；②创建时无立绘上传选项，且立绘缺失时聊天页回退显示头像大图；③背景需要三选一（上传 / 复用已存在 / 无背景纯色）。
- **立绘（第四阶段补充）**：新存角色目录 characters/{id}/portrait.{ext}（与头像同目录）；新端点 GET /api/characters/{id}/portrait（no-cache 协商缓存 304，同 avatar 模式）+ POST（创建请求内 portrait 字段）；前端 get_character_portrait 双位置检测（先角色目录→回退 assets）；**缺失时聊天页留空占位（名字首字浅底），不再回退头像、不指向其他角色文件**。现有 yuuka/mika 立绘位置不动。
- **背景三选一（互斥，服务端校验）**：①上传 → characters/{id}/background.{ext}；②复用已存在背景（background_copy_from="default" 或角色 id）→ `_find_background_file` 回退链（角色目录→assets/background/{id}→全局 background.jpg）**复制文件**，不改其他角色；③无背景 → character.json 写可选 background_color 字段（hex 正则 ^#RGB$|^#RRGGBB$ 校验），主视图纯色。全不提供=现有回退行为。新端点 GET /api/characters/{id}/background（304 同模式）；列表返回新增 background_color 字段。
- **前端（character_admin.py 创建页）**：立绘 file_uploader（可选）+ 背景三选一 radio（上传/复用 selectbox 列出「默认背景」+各角色/无背景 color_picker）；复用背景为**复制**语义（标注不影响原角色）。
- **测试 36/36 通过**：立绘（创建带立绘/无立绘留空 404/304 协商/其他角色未动）；背景三选一（上传/复用 yuuka 复制成功原文件未动/复用 default 无全局背景 400 明确/复用无背景角色 400/纯色写 background_color/互斥 400/非法颜色 400/恶意 copy_from 拒绝未穿越）；回归（优香未花 nagisa 在列、健康全绿、background_color 兼容 None、优香单聊、群聊、TTS）。
- **实施教训**：两处 edit 因"文件自上次读取后被修改"被拒而遗漏——CharacterCreate 字段（pydantic AttributeError）与 create_character 签名（TypeError unexpected keyword），测试第一轮全部 500 暴露；教训：edit 被拒后必须重做该 edit 并核对（不能只重做相邻部分），py_compile 只查语法不查名字解析。
- **遗留（已知）**：桐藤渚（nagisa）创建时无立绘选项，现立绘区显示占位（名字首字）——补立绘需删除重建（创建时有立绘选项）或后续给编辑页加立绘/背景上传；管理页编辑页暂无立绘/背景更换入口。
### 65. 编辑页补立绘/背景更换 + 主页立绘缺失留空（2026-10-19）
- **需求（用户复测第 64 条后提出）**：①主页立绘区仍显示头像大图（回退头像被 Hero CSS 拉伸成模糊大图）；②修改角色（编辑页）没有立绘/背景选项——第 64 条只做了创建页。
- **主页修复（streamlit_app.py render_hall_carousel）**：立绘缺失时不再回退头像 URL（`get_character_portrait(cid) or avatar_url(...)` 改为仅 `get_character_portrait(cid)`），Hero 立绘层条件化——无立绘留空（与聊天页占位策略一致，用户明确要求），有立绘才加 url 层。
- **编辑页补全（character_admin.py _render_edit_page）**：新增「立绘」区块（预览 + file_uploader + 更换按钮，同头像模式，uploader key 序号计数器）与「背景」区块（三选一 radio：上传/复用已存在/纯色 color_picker；radio 初值按当前背景状态智能设置——有 background_color 默认选纯色；当前背景状态描述行显示）。_leave_edit 清理新增 widget key。
- **新增 API（backend/main.py）**：`POST /api/characters/{id}/portrait`（更换立绘，base64，校验同头像）；`POST /api/characters/{id}/background`（三选一互斥：image 上传/copy_from 复制/color 纯色，纯色写 character.json background_color + 删背景文件，上传/复用清 background_color 字段）；GET profile 返回新增 portrait_ext（**双位置兼容**：角色目录→assets 旧位置，现有角色编辑页能预览旧立绘）/background_color/background_ext。
- **服务层（character_service.py）**：`update_portrait`（_validate_image + 换格式移开旧立绘备份回滚）；`update_background`（三选一互斥、全回滚、bg_color 优先级高于背景文件）；共用抽出 `_replace_image_file`（portrait/background 与 update_avatar 同模式）与 `_set_json_fields`（v=None 删字段原子写）；`_get_portrait_ext`/`_get_background_ext`。
- **测试 32/32 通过**：profile 新字段、立绘（更换/304 协商/换格式旧文件移开/角色 404）、背景三选一（上传/复用 yuuka 复制成功原文件未动/纯色写 background_color 删背景文件/纯色切上传字段清除/互斥/全空拒/非法颜色拒/copy_from 404）、删除含立绘背景清理；回归（优香未花 nagisa 在列、健康全绿、优香 profile 双位置预览 jpeg、单聊、群聊、TTS）。
- **范围**：llm/tts/fragment/CSS/群聊状态机零改动；编辑页更换立绘/背景复用创建时同一校验规则。
- **第 65 条补充（用户复测报告"已创建角色无法更改背景/立绘"）**：根因＝前端 8501 进程是 21:29 启动的旧进程（代码修改在 21:45），Streamlit 对**导入模块**（character_admin.py）变更的热重载未生效，运行的是旧版编辑页（实测 Playwright DOM：立绘/背景区块完全缺失、无异常框）。重启前端进程后全部区块渲染成功。**教训：修改 streamlit 导入的模块文件后必须重启 8501 进程（只等热重载不可靠）；此前"改前端只需等待热重载"的经验仅适用主脚本 streamlit_app.py**。

### 66. 角色创建目录结构与资源存储规范统一（以 yuuka/mika 为基准）（2026-10-20）
- **需求（用户提出）**：前端创建的角色（Kirifuji_Nagisa）目录结构与资源存储位置与现有 yuuka/mika 不一致——第 64/65 条把立绘/背景写进了 `characters/{id}/portrait|background.{ext}`（内聚设计），而现有角色约定是立绘 `frontend/assets/character/{id}.{ext}`、背景 `frontend/assets/background/{id}.{ext}`；且新建角色 character.json 缺 `subtitle` 字段。要求以 yuuka/mika 为基准统一，兼容现有角色，不移动 yuuka/mika 文件，未经确认不批量迁移（Kirifuji_Nagisa 迁移经用户确认后执行）。
- **统一规范（第 66 条起生效）**：`characters/{id}/` 只存 character.json + prompt.txt + avatar.{ext}（+可选 reference.wav）；立绘/背景存 `frontend/assets/{character|background}/{id}.{ext}`；character.json 写 subtitle（可选，字段结构与 yuuka/mika 一致）；tts 仍不写（可选配置，未配置无语音不算异常）；background_color 纯色模式为第四阶段新能力，保留为 json 字段。
- **服务层（character_service.py）**：`create_character` 加 subtitle 参数，立绘/背景改写 assets 规范位置（复用 `_replace_image_file`，含旧格式清理与备份回滚），失败清理含本次写入的 assets 文件；新增 `_write_image_to_assets`（update 用：写规范位置 + 清角色目录旧位置残留，残留先 rename `.replacing` 暂存、失败恢复、成功删除，残留不被白名单读取误取）；`update_portrait`/`update_background`（上传/复用）改写规范位置；`update_background` 纯色模式删两处旧文件；`delete_character` 同步清理 assets 该 ID 的立绘/背景（只删 `{id}.{ext}` 精确匹配，无 glob，失败并入 cleanup_warning 不影响删除）；读取优先级统一翻转为**规范位置优先、旧位置兼容回退**（`_get_portrait_ext`/`_get_background_ext` 补 assets 检测 + webp、`_find_background_file` 同步），旧位置文件（如有）仍可读，不破坏存量。
- **API（backend/main.py）**：CharacterCreate 加 `subtitle`；GET `/api/characters/{id}/portrait|background` 端点补规范位置回退（编辑页预览 URL 依赖这两个端点，迁移后立绘不再 404）。
- **前端**：character_admin.py 创建页加「副标题（可选）」输入框（key `_csubtitle_new`，_leave_create 同步清理）；streamlit_app.py `get_character_portrait`/`get_background` 优先级翻转为 assets 规范位置优先（扩展名清单补 webp 与后端白名单对齐）。
- **Kirifuji_Nagisa 迁移（用户确认后执行，可恢复移动）**：portrait.png → frontend/assets/character/Kirifuji_Nagisa.png，background.jpg → frontend/assets/background/Kirifuji_Nagisa.jpg；迁移后角色目录仅 avatar.png/character.json/prompt.txt，与 yuuka/mika 结构一致。
- **测试 46/46 通过**（cache/test_std66.py，接口级）：创建（角色目录仅 json/prompt/avatar、character.json 10 字段含 subtitle、立绘/背景落 assets）；资源读取（assets 直连 + 角色端点回退 + 头像 + profile portrait_ext 全 200）；更新（换立绘清旧位置残留、复用 yuuka 背景写规范位置且原文件未动、切纯色清文件写字段）；yuuka/mika 回归（头像 ext/subtitle/has_tts/tts_ok/立绘/背景/reference.wav/健康检查）；Nagisa 迁移后（目录结构一致、立绘/背景 200）；删除（目录+assets 立绘背景同步清理、列表无残留）；单聊冒烟（Nagisa 迁移后 + yuuka 各 200 且在角色人设内回复）。`git status` 无无关修改。测试脚本用完已清理。
- **教训**：验收脚本断言要与 API 实际暴露字段对齐（tts 出于安全只暴露 `has_tts` 布尔不暴露路径字典；健康检查角色数据在 `characters` 数组）——首轮 3 个"失败"全是断言写错，功能本身正常。
- **第 66 条补（用户复测后要求）**：侧边栏角色列表下方的「＋ 添加角色<span>即将上线</span>」纯 HTML 占位（创建功能上线前的视觉入口，无功能死按钮）替换为真实 st.button（key=sb_add_char，on_click=_nav_to_page("charadmin")），点击跳管理页创建角色；.sb-soon CSS 保留（「语音·聊天页开关」行仍在用）。
- **第 66 条补二（用户纠正）**：侧边栏「＋ 添加角色」此前跳「👤 角色管理」列表与底部入口功能重复，改为直达管理页创建视图——streamlit_app.py 新增 `_nav_to_create_character` 回调（_nav_to_page("charadmin") + 设 character_admin._CREATE_KEY），on_click 直达「➕ 创建角色」表单；管理页内既有「← 返回角色列表」行为不变。

### 67. 第五阶段：动态群聊管理（创建、邀请成员、移除成员）（2026-10-21）
- **需求**：固定群聊（GROUPS 硬编码）升级为动态群聊管理——用户自定义群名创建群聊、从已启用角色选初始成员；群聊界面邀请/移除成员；群 ID 程序安全生成；成员变更后下一次请求用最新列表；历史消息不因成员变更被删除/改写；不影响固定群与角色文件。
- **后端新增 services/group_service.py**：动态群持久化 backend/data/groups.json（原子写 tmp+replace；损坏备份回退为空，仿 character_state 模式）。群 ID 服务端生成（"g_"+uuid4 hex 12 位 = 14 字符），群名称只做显示绝不进路径（天然拒绝路径穿越）。校验全服务端独立：名称非空 ≤32 字、成员存在（404→400）+已启用（停用 400）、保序去重、≤8 人、邀请不可重复（400）、移除须在群内（400）、群不存在 404。移除只改本群 members 列表，不动角色目录/配置/头像/启停/群聊历史；允许移除到空群（前端发送时拦截提示）。
- **后端 API（main.py）**：GET /api/groups（动态群列表）；POST /api/groups（创建）；POST /api/groups/{gid}/members（邀请）；DELETE /api/groups/{gid}/members/{mid}（移除）。/api/group/chat 不改（members 参数化本就支持任意成员）。
- **前端（streamlit_app.py）**：①群视图合并——group_members/group_display_name 改查「固定 GROUPS + 动态群缓存」合并视图（函数签名不变，_do_send/_group_step/fragment 兜底调用点零改动）；load_groups_cache（操作后 _invalidate_groups 失效，fragment 内读缓存零网络）；_is_dynamic_group（g_ 前缀）。②侧边栏：群列表渲染合并视图（固定在前）+「＋ 创建群聊」按钮（_nav_to_create_group）。③创建页 render_group_create_page：名称输入 + 成员 multiselect（options=id、format_func 显示名，仅已启用角色）+ 创建/返回；成功后失效缓存并直接导航进新群。④render_app 路由加 group_create_mode 分支（优先于群聊/单聊）。⑤群聊页左栏新增「成员管理」面板 _render_group_member_panel：成员行（主题色圆点+名字，停用标注）+ 移除按钮（on_click 回调 _remove_group_member：服务端校验、成功失效缓存、失败保留原列表提示）；邀请 selectbox（未加入的已启用角色）+ 邀请按钮（_add_group_member）；固定群只读显示。⑥防护：_do_send 空群拦截（回滚 user 消息、错误只显示不进历史、不动状态机）；fragment 欢迎语按成员数动态（空群提示先邀请）。
- **关键机制（需求映射）**：成员变更后下一轮生效——_group_send 状态机对 members 做了本轮快照（发送中途改成员不影响本轮），下轮 _do_send 重新读缓存即最新列表；历史隔离/保留——group_conversations[gid] 按 gid 独立存储，移除成员只影响后续 members 参数，历史 role=角色id 的旧消息原样保留；不覆盖已有群——ID 服务端 uuid 生成查重；不影响固定群——动态群独立文件，固定群仍在前端 GROUPS。
- **测试 26/26 通过**（cache/test_group5.py 接口级，用完已清理）：创建（合法/空名/空成员/无效成员/停用成员/超长名/重复成员保序去重/路径穿越名称仅作显示/两次创建 ID 不同）；邀请（成功列表更新/重复 400/无效 400/群 404/三成员群聊各一条回复全 ok）；移除（成功/再移除 400/群 404/mika 角色完好/移除后请求不含 mika 且历史保留）；固定群（不在动态群接口/群聊回归正常两回复）。测试群数据已清空（groups.json 置空重启验证）。
- **教训**：测试脚本 api() 封装把 timeout=30 写死在 requests.request 调用里，调用方再用 **{"timeout": 300} 覆盖会得到 TypeError: got multiple values for keyword（被 except 吞成 HTTP 0 假失败）——封装函数的默认参数应放进 kw 让调用方可覆盖。

### 68. 固定群补成员管理 + 聊天页日历/语音图标滚动漂移修复（2026-10-21）
- **需求（用户验收第 67 条后提出两问题）**：①固定群聊（yuuka_mika）没有成员管理（邀请/移除），只有动态群有；②群聊页日历📅与语音🔊图标随页面滚动漂移（脱离工具栏悬在错误位置）。要求最小范围修改、不迁移固定群、不破坏 GROUPS 与动态群隔离、不动聊天 fragment/CSS 结构/图标功能样式。
- **问题一（固定群成员管理）后端**：group_service.py 加 FIXED_GROUPS 注册表（与前端 GROUPS 同步：yuuka_mika → 优香 × 未花 → [yuuka, mika]）。固定群不迁移：默认成员兜底，成员变更存 groups.json「覆盖条目」（fixed=true），删除覆盖即恢复默认；名称恒以注册表为准。_load 分流（注册表 id→覆盖 / g_ 前缀→动态群 / 其他忽略）；_save 合并写；list_groups 返回动态群+覆盖条目（仅被管理过的固定群出现，无覆盖时行为与旧版完全一致）；get_group/add_member/remove_member 支持固定群（写覆盖条目不动注册表）。**最后一名成员保护（所有群统一）**：remove_member 在成员 ≤1 时 400「群内至少保留一名成员」——第 67 条「允许移除到空群」语义废止（前端空群拦截保留为二道防线）。**修复过程中发现并删除了残留的旧版重复 remove_member 定义（Python 后定义覆盖前者，导致保护实际失效）**。main.py 4 个群端点 docstring 同步更新。
- **问题一前端（streamlit_app.py）**：_all_groups 读缓存时识别 fixed=true 条目覆盖 GROUPS 对应项 members（名称仍以本地 GROUPS 为准，双保险）；_render_group_member_panel 去掉「固定群只读」——全群（固定+动态）统一「👥 成员管理」标题、移除按钮、邀请 selectbox；_is_dynamic_group 保留作语义辅助（暂无调用方）；回调 _add/_remove_group_member 本就通用零改动。
- **问题二（图标滚动漂移）根因与修复**：日历/语音图标是 components.html iframe，容器 CSS 隐藏占位，iframe 内 JS 的 place() 用 cal-slot/voice-slot getBoundingClientRect 把容器设 position:fixed 定位到 slot 处——但 place() 只在初始（rAF 双帧/setTimeout 300/1000ms）与 resize 时执行，无滚动监听：页面滚动后 slot 上移而 fixed 图标留在视口原位 → 悬空漂移。修复（最小改动）：cal_js 与 voice_js 各加一行 `P.defaultView.addEventListener("scroll",place,true)`（捕获阶段监听，任意内部滚动容器滚动均触发 place 重定位）。CSS 结构/图标功能/点击/样式零改动。
- **测试 21/21 API（cache/test68.py）+ 9/9 Playwright DOM（cache/test68_icon.py）通过，脚本用完已清理**：固定群（无覆盖不出现在列表=旧版兼容/邀请 Nagisa 成功 3 人/覆盖条目 fixed=true 名称注册表值/重复添加 400/移除回默认 2 人/移除 yuuka 剩 mika/最后一名保护 400 且成员不变/群 404/角色 400/覆盖后群聊真实发送 mika 单条回复正常=下轮生效）；动态群回归（创建 g_ 前缀/邀请/移除/最后一名保护/无 fixed 标记）；用户动态群「茶话会」全程不受影响（测试前备份 groups.json、测后恢复原文件并重启后端验证）；历史保留由代码结构保证（group_service 无任何历史操作，group_conversations[gid] 前端 session 隔离）。图标（Playwright 1400×900 真实浏览器）：两图标容器 position:fixed、滚动前后对齐 slot 偏差 0.0px；注入 flex-shrink:0 占位强制产生滚动后 slot 位移 -600px、图标位移 -600px 精确跟随（旧代码无监听时图标位移 0 会偏差 600px）。**注：Streamlit stMain 是 flex 容器，注入占位必须 flex-shrink:0 否则被压缩到 0 高度不产生滚动。**
- **回归**：单聊（优香回复正常）/固定群聊（覆盖成员下正常生成）/TTS available/模型 qwen3:8b 预加载 ok/三角色全启用。前后端进程均已用最新代码重启（8000/8501）。

### 69. 第六阶段：动态群聊改名与删除（2026-10-21）
- **需求**：动态群聊补改名与删除——改名仅动态群（固定群拒绝）、群 ID 不变、名称只做显示不进路径；删除仅动态群（固定群拒绝）、幂等语义明确、不碰角色文件/启停/TTS、失败保留原配置；前端改名保存后立即更新侧边栏与标题、取消不改；删除必须二次确认（明示删的是群聊非角色）、取消零修改、删除后清本群历史并安全切换会话。不改历史存储架构、不动 fragment 状态机。
- **后端（group_service.py）**：新增 `rename_group(gid, name)`——固定群 400「固定群不支持改名」、404、名称去首尾空白/拒空/纯空白/超长（上限沿用 GROUP_NAME_MAX=32，与创建一致；用户建议的 40 字会打破既有创建上限的已验收行为，故不采用）；只改 name 字段（ID/成员/其他群不动），同名幂等直接成功；`_save` 失败回滚内存旧名。新增 `delete_group(gid)`——固定群 400、不存在 404（幂等明确：已删群再删返回 404，与既有成员端点约定一致）；从 `_groups` 移除并防御性清理同 ID 覆盖条目（正常不会存在）；`_save` 失败恢复内存条目（文件与内存一致）；群名称绝不拼接路径（按 ID 查内存字典）。
- **后端 API（main.py）**：`POST /api/groups/{gid}/name`（body `{name}`，模型 GroupRename）；`DELETE /api/groups/{gid}`。错误行为：改名 400（固定群/空名/纯空白/超长>32）、404（群不存在）、500（写失败回滚）；删除 400（固定群）、404（群不存在/已删）。
- **前端（streamlit_app.py）**：群聊页左栏新增「⚙️ 群设置」面板 `_render_group_settings_panel`（**仅动态群**显示，`_is_dynamic_group` 首个真实调用方；固定群无此面板）。改名：「✏️ 修改群名称」→ 编辑态 text_input（初值=当前名，编辑态首次渲染前初始化避开 widget key 赋值限制）→「💾 保存名称」/「取消」；保存成功 `_invalidate_groups()` 使 fragment rerun 重拉缓存——侧边栏与群聊页标题立即更新（群 ID 与历史不变）；取消清编辑态零修改。删除：「🗑️ 删除群聊」→ 二次确认区（st.warning 明示「仅删除该群聊与成员列表，**不删除任何角色、立绘、语音或文件**」）→「❗ 确认删除」/「取消」；确认成功后 `_confirm_delete` 清理本群 session（group_conversations[gid] 本群历史 / `_group_send_` 发送状态机 / `_group_op_`、`_ginvite_`、改名删除各操作键——只清该群 ID，其他群与单聊历史不动）+ 失效缓存 + current_group_id/current_character_id 置 None 安全切回主页。全部 on_click 回调模式（与成员管理同款，fragment 外交互，不触碰聊天 fragment 状态机）。
- **测试 39/39 API（test69.py 两阶段，用完已清理）**：改名（成功/重启后端持久化/空名 400/纯空白 400/33 字 400/恰 32 字成功/去首尾空白/404/固定群 400 且名称未变/同名幂等/ID 与成员不变/其他群零影响）；删除（成功/重启后不重现/固定群 400/已删群再删 404 幂等/不存在 404/groups.json 条目消失/其他群零影响）；零影响快照对比（角色列表+启停、角色目录文件、立绘背景 assets、TTS status 删除前后全一致）；回归（创建/邀请/移除/最后一名保护 400/固定群成员管理覆盖条目/单聊/群聊 2 条回复/模型状态）。
- **浏览器验证 19/19（test69_ui.py Playwright，真实 Chromium）**：动态群显示群设置面板（含改名+删除入口）；改名输入框初值=当前名→保存后**标题与侧边栏立即更新**+成功提示；取消改名后输入内容不生效；删除出现二次确认（含「不删除任何角色」提示）→取消后群仍在（前端+后端双验证）→确认删除后**安全切回主页**（开始聊天入口出现）、侧边栏群消失、无 pageerror、用户群茶话会仍在；固定群（优香×未花）正常进入、**无群设置面板**、成员管理面板仍在。
- **教训（测试脚本自身两轮 bug，非产品问题）**：①tuple 经 JSON 序列化变 list，跨进程快照对比须统一用 list（否则「零变化」断言假失败）；②测试断言要核对实际状态机——移除 mika 后剩 [yuuka]，再「恢复 yuuka」实为重复添加被 400（正确断言应是恢复 mika 回初始成员）；③**Streamlit 按钮标签是 Markdown——群名含 `_下划线_` 会被解析成斜体标记导致下划线消失**，Playwright `has-text` 匹配不到（测试数据勿用 Markdown 特殊字符）；④当前群在侧边栏渲染为 HTML 激活行（非 st.button），断言须用 `[data-testid="stSidebar"] >> text=` 而非 button 选择器；⑤ `URL.split(':')[0]` 取 http 而非 host，直接写完整 URL。
- **回归**：前后端已重启（8000/8501），服务正常；用户 groups.json 测前备份测后恢复（茶话会 g_6a80f1d940e9，成员 [Kirifuji_Nagisa]——用户本轮自行移除了 yuuka，按最新状态恢复）；全部改动保持工作区未提交。
