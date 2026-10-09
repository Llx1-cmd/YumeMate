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
