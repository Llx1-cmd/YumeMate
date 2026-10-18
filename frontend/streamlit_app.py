import streamlit as st
import streamlit.components.v1 as components
import requests
import sys
import time
import base64
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from config import settings

from character_admin import render_character_admin_page

BACKEND_URL = f"http://{settings.BACKEND_HOST}:{settings.BACKEND_PORT}"


# ==================== 工具函数 ====================

def get_user_avatar_html(size=36):
    """读取用户头像（本地文件），找不到用 emoji（样式由 .chat-avatar CSS 控制）"""
    for name in ["user.png", "user.jpg", "user.jpeg"]:
        p = Path(__file__).parent / "assets" / name
        if p.exists():
            with open(p, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
            return f'<img src="data:image/png;base64,{img_b64}" alt="user">'
    return '<span style="font-size:18px;">👤</span>'


def get_character_avatar_html(character_id, size=36):
    """从后端 /api/characters/{id}/avatar 拿头像（样式由 .chat-avatar CSS 控制）"""
    url = f"{BACKEND_URL}/api/characters/{character_id}/avatar"
    return f'<img src="{url}" alt="avatar">'


def get_character_portrait(character_id):
    """读取本地角色立绘（assets/character/{id}.png 等），找不到返回 None（回退头像）"""
    for name in [f"{character_id}.png", f"{character_id}.jpg", f"{character_id}.jpeg"]:
        p = Path(__file__).parent / "assets" / "character" / name
        if p.exists():
            with open(p, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
            return f"data:image/png;base64,{img_b64}"
    return None


def get_background(character_id=None):
    """读取背景图：优先按角色（{id}.png/jpg），找不到回退全局 background.jpg，都没有返回 None"""
    candidates = []
    if character_id:
        candidates += [f"{character_id}.png", f"{character_id}.jpg", f"{character_id}.jpeg"]
    candidates += ["background.jpg", "background.png", "background.jpeg"]
    for fname in candidates:
        p = Path(__file__).parent / "assets" / "background" / fname
        if p.exists():
            with open(p, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
            return f"data:image/png;base64,{img_b64}"
    return None


def fetch_characters():
    """从后端拉取角色列表"""
    try:
        r = requests.get(f"{BACKEND_URL}/api/characters", timeout=5)
        if r.status_code == 200:
            return r.json().get("characters", [])
    except requests.exceptions.ConnectionError:
        pass
    except Exception as e:
        st.error(f"加载角色失败：{e}")
    return []


def send_chat_message(message, history, character_id):
    """调用后端 /api/chat。返回 (ok, text)：
    ok=True 时 text 为角色回复；ok=False 时 text 为错误信息（只用于 UI 展示，
    不写入聊天历史）。异常类型显式区分超时/连接失败/其他，不靠字符串前缀判断。"""
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/chat",
            json={
                "message": message,
                "history": history,
                "character_id": character_id,
            },
            timeout=120,
        )
        if response.status_code == 200:
            return True, response.json().get("reply", "抱歉，我暂时无法回复。")
        return False, f"服务错误（HTTP {response.status_code}）"
    except requests.exceptions.Timeout:
        return False, "回复超时（模型可能正在加载或后端繁忙，稍后重试即可，这条消息不会计入对话记录）"
    except requests.exceptions.ConnectionError:
        return False, "无法连接到后端服务（请确认 8000 端口已启动）"
    except Exception as e:
        return False, f"请求异常：{type(e).__name__}"


def send_group_message(message, history, members):
    """调用后端 /api/group/chat：共享历史 + members 顺序生成。

    返回 (ok, replies, err)：
    ok=True 时 replies 为 [{"role","content","ok"}, ...]（单项 ok=False 表示该成员
    生成失败，前端只显示不写历史）；ok=False 表示请求级失败（replies=None，err 为
    错误信息）。异常类型显式区分，不靠字符串前缀判断。
    """
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/group/chat",
            json={
                "message": message,
                "history": history,
                "members": members,
            },
            timeout=300,
        )
        if response.status_code == 200:
            return True, response.json().get("replies", []), None
        return False, None, f"服务错误（HTTP {response.status_code}）"
    except requests.exceptions.Timeout:
        return False, None, "回复超时（模型可能正在加载或后端繁忙，稍后重试即可，这条消息不会计入对话记录）"
    except requests.exceptions.ConnectionError:
        return False, None, "无法连接到后端服务（请确认 8000 端口已启动）"
    except Exception as e:
        return False, None, f"请求异常：{type(e).__name__}"


# ==================== Session 初始化 ====================

# 群聊定义（成员列表概念；扩展更多群/成员只改这里，后端 members 参数化不写死）
# 每个群：显式群名 + members 列表（按回复顺序）
GROUPS = {
    "yuuka_mika": {
        "name": "优香 × 未花",
        "members": ["yuuka", "mika"],
    },
}


def group_members(group_id):
    """按群 id 取成员列表（未知群返回空列表）"""
    return GROUPS.get(group_id, {}).get("members", [])


def group_display_name(group_id):
    """群显示名（GROUPS 里显式配置）"""
    return GROUPS.get(group_id, {}).get("name", group_id)


def _member_aliases(member_id, characters):
    """成员的称呼候选（用于点名匹配）：全名 + 名（name[-2:] 简称）+ id"""
    c = next((x for x in characters if x["id"] == member_id), None)
    if not c:
        return [member_id]
    name = c.get("name", member_id)
    aliases = [name]
    if len(name) >= 2 and name[-2:] != name:
        aliases.append(name[-2:])
    aliases.append(member_id)
    return aliases


def detect_mention_order(message, members, characters):
    """明确点名角色时该角色优先回答：按消息中成员称呼首次出现位置排序。

    简单可靠的字符串匹配（无 AI 意图识别）：只点一人 → 该人排首；同时点名
    多人 → 按出现位置排序；未点名的成员保持默认顺序排后；无点名 → 原顺序。
    """
    text = (message or "").lower()
    pos = {}
    for mid in members:
        best = None
        for a in _member_aliases(mid, characters):
            i = text.find(a.lower())
            if i >= 0 and (best is None or i < best):
                best = i
        if best is not None:
            pos[mid] = best
    if not pos:
        return list(members)
    mentioned = sorted(pos, key=pos.get)
    rest = [m for m in members if m not in pos]
    return mentioned + rest


def init_session_state():
    """初始化 session_state（核心：按角色分存单聊历史，群聊历史独立存储）"""
    if "conversations" not in st.session_state:
        # 单聊: {character_id: [{"role":"user"/"assistant","content":"..."}, ...]}
        st.session_state.conversations = {}
    if "group_conversations" not in st.session_state:
        # 群聊: {group_id: [{"role":"user"/"yuuka"/"mika","content":"..."}, ...]}
        # 与单聊 conversations 完全分开，单聊/群聊历史互不污染
        st.session_state.group_conversations = {}
    if "current_character_id" not in st.session_state:
        # None = 入口页；"settings" = 设置页；其他 = 单聊页
        st.session_state.current_character_id = None
    if "current_group_id" not in st.session_state:
        # None = 不在群聊页；非空 = 群聊页（路由优先于单聊）
        st.session_state.current_group_id = None
    if "characters_cache" not in st.session_state:
        st.session_state.characters_cache = None
    # 侧边栏各主分类的展开状态（替代 st.expander，避免图标字体回退问题）
    if "sidebar_expanded" not in st.session_state:
        st.session_state.sidebar_expanded = {
            "characters": True,   # 角色默认展开
            "groups": False,
            "voice": False,
        }
    # 聊天大厅 Carousel 当前显示的角色下标
    if "hall_index" not in st.session_state:
        st.session_state.hall_index = 0
    # 全局语音开关（聊天页右上角 🔊；刷新后恢复默认开启，不做持久化）
    if "voice_enabled" not in st.session_state:
        st.session_state.voice_enabled = True
    # 已自动播放过的语音消息（key = "角色id:消息下标"），避免重绘时重复播放
    if "played_audio_keys" not in st.session_state:
        st.session_state.played_audio_keys = set()
    # GPT-SoVITS 在线状态（整页渲染时检查，60 秒缓存；fragment 重绘不发起网络请求）
    if "tts_up" not in st.session_state:
        st.session_state.tts_up = False
    if "tts_checked_at" not in st.session_state:
        st.session_state.tts_checked_at = 0.0


def get_current_messages(key_base, mode="single"):
    """取当前会话的消息列表（若不存在则初始化）。

    mode="single"：单聊，key_base=角色id，存 conversations；
    mode="group"：群聊，key_base=群id，存 group_conversations（独立存储保证隔离）。
    """
    if mode == "group":
        store = st.session_state.group_conversations
    else:
        store = st.session_state.conversations
    if key_base not in store:
        store[key_base] = []
    return store[key_base]


# ==================== 左侧折叠导航栏 ====================

@st.fragment
def render_sidebar():
    """渲染侧边栏：品牌区 + 角色列表（头像行）+ 更多功能 + 底部辅助导航。

    本次只改视觉呈现（角色陪伴应用风格的角色栏），交互逻辑保持原样：
    用 @st.fragment 隔离：侧边栏自身的 widget 交互（如「角色」分组展开/收起）
    只重跑本 fragment，主区（character-info / 立绘 / 聊天 fragment）保持不动，
    避免整页 rerun 导致角色卡与 emoji 按钮闪烁。
    侧边栏里的页面跳转按钮仍用 st.rerun()（app 作用域）整页重跑——切页本就需要。
    """
    with st.sidebar:
        # ---- 品牌区（轻盈：标题明显，副标题小而弱）----
        st.markdown(
            '<div class="sb-brand">'
            '<div class="sb-brand-title">💬 聊天大厅</div>'
            '<div class="sb-brand-sub">多角色 AI 陪伴</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # ---- 角色（可折叠小标题；展开/收起逻辑与 fragment rerun 原样不动）----
        _render_sidebar_section(
            key="characters",
            icon="",
            title="角色",
        )
        if st.session_state.sidebar_expanded["characters"]:
            characters = load_characters_cache()
            if not characters:
                st.warning("⚠️ 无法加载角色")
                if st.button("🔄 重新加载", use_container_width=True, key="reload_chars"):
                    st.session_state.characters_cache = None
                    st.rerun()
            else:
                _render_sidebar_characters(characters)
                # 视觉入口，无功能（不为此改后端）
                st.markdown(
                    '<div class="sb-add">＋ 添加角色<span class="sb-soon">即将上线</span></div>',
                    unsafe_allow_html=True,
                )

        # ---- 更多功能（群聊已上线；语音随聊天页开关）----
        st.markdown('<div class="sb-more-title">更多功能</div>', unsafe_allow_html=True)
        characters = load_characters_cache()
        for gid in GROUPS:
            gname = group_display_name(gid)
            if st.session_state.current_group_id == gid:
                # 群聊激活行（HTML 渲染，与选中角色行同风格）
                st.markdown(
                    '<div class="sb-char sb-char-active" style="background:rgba(185,166,222,0.14);border-left-color:#B9A6DE;">'
                    '<div class="sb-avatar sb-avatar-fallback" style="background:#B9A6DE;">👥</div>'
                    f'<div class="sb-info"><div class="sb-name">{gname}</div>'
                    '<div class="sb-status"><span class="dot"></span>群聊中</div></div></div>',
                    unsafe_allow_html=True,
                )
            else:
                if st.button(f"👥 群聊 · {gname}", key=f"nav_group_{gid}", use_container_width=True):
                    st.session_state.current_group_id = gid
                    st.rerun()
        st.markdown(
            '<div class="sb-more-row">○ 语音<span class="sb-soon">聊天页开关</span></div>',
            unsafe_allow_html=True,
        )

        # ---- 弹性空间：把底部导航压到 Sidebar 底部（高度链见 .sb-spacer 的 CSS 注释）----
        st.markdown('<div class="sb-spacer"></div>', unsafe_allow_html=True)

        # ---- 底部辅助导航（逻辑不变：管理 / 设置 / 返回主页）----
        if st.button("👤 角色管理", use_container_width=True, key="nav_admin"):
            st.session_state.current_character_id = "charadmin"
            st.session_state.current_group_id = None
            st.rerun()

        if st.button("⚙ 设置", use_container_width=True, key="nav_settings"):
            st.session_state.current_character_id = "settings"
            st.session_state.current_group_id = None
            st.rerun()

        if st.button("🏠 返回主页", use_container_width=True, key="nav_home"):
            st.session_state.current_character_id = None
            st.session_state.current_group_id = None
            st.rerun()


def _hex_to_rgb(hex_color):
    """'#RRGGBB' → (r, g, b)，用于把角色主题色转成带透明度的背景色"""
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _sidebar_char_html(char, active):
    """当前选中角色的整行 HTML（头像 + 名字 + 在线状态 + 主题色轻盈高亮）。

    非选中角色不在此渲染——它们必须走 st.button 保持可点击切换，
    头像/状态用注入的 CSS 画在按钮上（见 _sidebar_char_css）。
    """
    cid = char["id"]
    name = char["name"]
    accent = char.get("color") or "#FF6B9D"
    r, g, b = _hex_to_rgb(accent)
    if char.get("avatar_ext"):
        avatar = f'<img class="sb-avatar" src="{BACKEND_URL}/api/characters/{cid}/avatar" alt="{name}">'
    else:
        # 无头像兜底：主题色圆底 + 名字首字（不创建空图片文件）
        avatar = f'<div class="sb-avatar sb-avatar-fallback" style="background:{accent};">{name[0]}</div>'
    return (
        f'<div class="sb-char sb-char-active" style="--sb-accent:{accent};'
        f'background:rgba({r},{g},{b},0.12);border-left-color:{accent};">'
        f'{avatar}<div class="sb-info">'
        f'<div class="sb-name">{name}</div>'
        f'<div class="sb-status"><span class="dot"></span>在线</div>'
        f'</div></div>'
    )


def _sidebar_char_css(char):
    """非选中角色按钮的样式：头像画在按钮左侧 + 名字/在线两行排版。

    Streamlit 的 button 不支持内嵌 HTML，所以头像用 background-image 注入，
    在线状态用 ::after 追加一行；每个角色一份规则，角色增多自然纵向增长。
    """
    cid = char["id"]
    accent = char.get("color") or "#FF6B9D"
    # 选择器统一加 [data-testid="stSidebar"] 前缀提高特异性：
    # 这些规则注入在侧边栏（DOM 靠前），若与主区注入的通用按钮规则同特异性会因顺序靠前而落败
    sel = f'[data-testid="stSidebar"] .st-key-nav_{cid} button'
    rules = [
        f'{sel} {{',
        'background-color: transparent !important;'
        'border: none !important; box-shadow: none !important;'
        'border-left: 3px solid transparent !important;'
        'border-radius: 12px !important;'
        'min-height: 52px !important;'
        'display: flex !important; flex-direction: column !important;'
        'align-items: flex-start !important; justify-content: center !important;'
        'font-size: 14px !important; font-weight: 600 !important;'
        'color: var(--text-main) !important;'
        'transition: background-color 0.15s ease, transform 0.15s ease !important;'
        '}\n',
        f'{sel}:hover {{',
        f'background-color: rgba(255, 255, 255, 0.7) !important;',
        f'color: {accent} !important;',
        '}\n',
        f'{sel}::after {{',
        'content: "● 在线" !important;'
        'font-size: 11px !important; font-weight: 400 !important;'
        'color: var(--ok); opacity: 0.75; margin-top: 1px;'
        '}\n',
    ]
    if char.get("avatar_ext"):
        url = f"{BACKEND_URL}/api/characters/{cid}/avatar"
        rules.append(
            f'{sel} {{'
            f'background-image: url("{url}") !important;'
            'background-repeat: no-repeat !important;'
            'background-position: 12px center !important;'
            'background-size: 34px 34px !important;'
            'padding-left: 56px !important;'
            '}\n'
        )
    else:
        rules.append(f'{sel} {{ padding-left: 15px !important; }}\n')
    return "".join(rules)


def _render_sidebar_characters(characters):
    """角色列表（纯视觉层）：数据仍来自 /api/characters，点击切换沿用原 nav_{id} 按钮逻辑"""
    st.markdown(
        "<style>" + "".join(_sidebar_char_css(c) for c in characters) + "</style>",
        unsafe_allow_html=True,
    )
    for char in characters:
        cid = char["id"]
        if st.session_state.current_character_id == cid and not st.session_state.current_group_id:
            st.markdown(_sidebar_char_html(char, active=True), unsafe_allow_html=True)
        else:
            if st.button(char["name"], key=f"nav_{cid}", use_container_width=True):
                st.session_state.current_character_id = cid
                st.session_state.current_group_id = None
                st.rerun()


def load_characters_cache():
    """带缓存的角色加载"""
    if st.session_state.characters_cache is None:
        st.session_state.characters_cache = fetch_characters()
    return st.session_state.characters_cache


def _render_sidebar_section(key: str, icon: str, title: str):
    """用普通按钮 + 条件渲染模拟可折叠的主分类。

    之所以不直接用 st.expander：Streamlit 自带的 expander 标题里会渲染 Material Icons 字体图标，
    在字体没加载到时会显示成 "_arrow_right" 这种回退字样，污染 UI。
    改用纯 emoji + 文字 + 旋转箭头标记，自己完全控制显示。
    """
    expanded = st.session_state.sidebar_expanded[key]
    # 标题栏（带点击切换）
    arrow = "▼" if expanded else "▶"
    label = f"{arrow}  {icon}  {title}"
    if st.button(label, key=f"section_{key}", use_container_width=True):
        st.session_state.sidebar_expanded[key] = not expanded
        # 纯 UI 展开/收起：只重跑侧边栏 fragment，不触发整页 rerun（否则主区会闪）
        st.rerun(scope="fragment")


# ==================== 入口页（聊天大厅 · 角色 Hero Carousel） ====================

def _hall_step(delta):
    """左右切换 on_click 回调：回调先于脚本执行，改完索引无需再显式 rerun"""
    count = len(st.session_state.get("characters_cache") or [])
    if count <= 1:
        return
    cur = st.session_state.get("hall_index", 0)
    st.session_state.hall_index = (cur + delta) % count
    # 记录切换方向 + 自增序号，供 Hero 滑入动画生成唯一的 animation-name：
    # CSS 动画只在 animation-name 变化时重放，序号保证每次切换都触发
    st.session_state.hall_dir = delta
    st.session_state.hall_anim_seq = st.session_state.get("hall_anim_seq", 0) + 1


@st.fragment
def render_hall_carousel(characters):
    """角色大厅主区：Hero 式角色展示 + 左右切换 + 位置指示点。

    用 @st.fragment 隔离（与侧边栏、聊天区同款策略）：切换角色只重跑本区域，
    不触发整页 rerun，避免 Hero 场景图/立绘整体重绘造成的闪烁。
    仅为新增隔离，不改动聊天页既有的 fragment / rerun 结构。
    """
    count = len(characters)
    # 角色增删后索引可能越界，收敛回 0
    idx = st.session_state.get("hall_index", 0)
    if not isinstance(idx, int) or not (0 <= idx < count):
        idx = 0
        st.session_state.hall_index = 0

    char = characters[idx]
    cid = char["id"]
    name = char["name"]
    subtitle = char.get("subtitle", "")
    accent = char.get("color", "#FF6B9D")
    # 欢迎语优先取角色数据里的 greeting 字段（character.json），没有则用通用兜底文案（不对任何具体角色写死）
    raw_greeting = (char.get("greeting") or "").strip()
    if raw_greeting:
        greeting = f"「{raw_greeting}」"
    else:
        greeting = f"「你好呀，我是{name}～今天想和我聊点什么？」"

    bg = get_background(cid)
    portrait = get_character_portrait(cid) or f"{BACKEND_URL}/api/characters/{cid}/avatar"

    # 左右切换按钮放在 Hero 卡片外侧（vertical_alignment 让它们与卡片垂直居中）。
    # 只有一个角色时按钮置灰：保留"这里可以切换"的视觉提示，但不虚构其他角色。
    col_prev, col_hero, col_next = st.columns([1, 20, 1], vertical_alignment="center")
    with col_prev:
        st.button("‹", key="hall_prev", disabled=(count <= 1),
                  on_click=_hall_step, args=(-1,))

    with col_hero:
        with st.container(key="hall_hero"):
            # Hero 的三层视觉（文字侧柔光 / 立绘 / 场景）全部用 CSS 背景层叠加，
            # 而不是绝对定位的 <img>：Streamlit 的元素容器自身是 position:relative 且
            # 高度为 0，绝对定位的图片在里面会塌成 0 高（实测 boundingRect height=0）。
            # 背景层天然垫在所有内容之下，文字/按钮不需要再做 z-index 抬升。
            layers, sizes, positions, repeats = [], [], [], []
            # 1) 顶部柔光：左侧接近白，向右渐隐，保证文字可读
            layers.append(
                "linear-gradient(96deg, rgba(255,252,255,0.97) 0%, rgba(253,246,252,0.90) 24%, "
                "rgba(250,240,250,0.52) 44%, rgba(250,240,250,0.10) 62%, rgba(250,240,250,0) 76%)"
            )
            sizes.append("100% 100%")
            positions.append("center")
            repeats.append("no-repeat")
            # 2) 角色立绘（透明 PNG），贴底靠右
            layers.append(f'url("{portrait}")')
            sizes.append("auto 94%")
            positions.append("right 2% bottom")
            repeats.append("no-repeat")
            # 3) 场景背景
            if bg:
                layers.append(f'url("{bg}")')
                sizes.append("cover")
                positions.append("center")
                repeats.append("no-repeat")

            hero_css = (
                '<style>.st-key-hall_hero {'
                f'background-image: {", ".join(layers)} !important;'
                f'background-size: {", ".join(sizes)} !important;'
                f'background-position: {", ".join(positions)} !important;'
                f'background-repeat: {", ".join(repeats)} !important;'
                '}'
            )
            # 切换滑入动画：name 里嵌自增序号，每次切换都独一无二 → 浏览器重放动画；
            # 方向跟随按钮（→ 切下一个从右侧滑入，← 切上一个从左侧滑入）；
            # 首次渲染 seq=0 不动画（页面刚打开不需要动）；
            # 系统开启"减少动态效果"时禁用（prefers-reduced-motion）
            seq = st.session_state.get("hall_anim_seq", 0)
            if seq > 0:
                from_x = 64 if st.session_state.get("hall_dir", 1) > 0 else -64
                hero_css += (
                    f'.st-key-hall_hero {{ animation: hall-in-{seq} 0.45s '
                    'cubic-bezier(0.22, 0.61, 0.36, 1) both; }'
                    f'@keyframes hall-in-{seq} {{'
                    f'from {{ transform: translateX({from_x}px); opacity: 0.15; }} '
                    'to { transform: translateX(0); opacity: 1; } }'
                    '@media (prefers-reduced-motion: reduce) { '
                    '.st-key-hall_hero { animation: none; } }'
                )
            st.markdown(hero_css + '</style>', unsafe_allow_html=True)

            st.markdown(
                '<div class="hall-text">'
                f'<h1 class="hall-name">{name}</h1>'
                f'<div class="hall-accent" style="background:{accent};"></div>'
                f'<div class="hall-sub">{subtitle}'
                '<span class="hall-online"><span class="dot"></span>在线</span></div>'
                f'<p class="hall-greeting">{greeting}</p>'
                '</div>',
                unsafe_allow_html=True,
            )
            # 进入聊天页：沿用原来的页面切换逻辑（切页本就需要整页 rerun）
            if st.button("开始聊天 →", key="hall_start", type="primary"):
                st.session_state.current_character_id = cid
                st.session_state.current_group_id = None
                st.rerun()

    with col_next:
        st.button("›", key="hall_next", disabled=(count <= 1),
                  on_click=_hall_step, args=(1,))

    # 底部位置指示点
    st.markdown(
        '<div class="hall-dots">'
        + "".join(
            '<span class="hall-dot%s"></span>' % (" active" if i == idx else "")
            for i in range(count)
        )
        + '</div>',
        unsafe_allow_html=True,
    )


def render_home_page():
    """聊天大厅入口页：Hero 式角色展示 + 多角色左右切换（角色数据始终来自 /api/characters）"""

    characters = load_characters_cache()

    st.markdown(
        '<div class="hall-head">'
        '<div class="hall-head-title">💬 聊天大厅</div>'
        '<div class="hall-head-sub">选择一个角色，开始属于你们的故事</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    if not characters:
        st.error("❌ 无法加载角色列表，请确认后端是否启动")
        st.code("""
cd F:\\YuukaChat\\backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
""", language="bash")
        if st.button("🔄 重新加载", type="primary"):
            st.session_state.characters_cache = None
            st.rerun()
        return

    render_hall_carousel(characters)


# ==================== 聊天页 ====================

# 常用表情（点击追加到输入框）
EMOJIS = [
    "😀", "😁", "😂", "🤣", "😊", "😍", "😘", "😜",
    "🤔", "😭", "😅", "😇", "🙃", "😉", "😎", "🤗",
    "😴", "🤯", "🥰", "😳", "🥺", "😤", "🤬", "😱",
    "👍", "👎", "👏", "🙏", "💪", "🤝", "❤️", "💔",
    "🎉", "✨", "🔥", "💯", "⭐", "🌸", "💕", "🐱",
]


def _append_emoji(emoji, input_key):
    """表情按钮 on_click 回调：追加 emoji 到输入框（回调在脚本前执行，可安全改写 widget 值）"""
    st.session_state[input_key] = st.session_state.get(input_key, "") + emoji


def _prepare_send(key_base, mode="single"):
    """发送按钮 on_click 回调：暂存待发送文本并清空输入框。
    群聊发送中（分步状态机未走完）时忽略本次，等上一轮全部回复完成。"""
    if mode == "group" and st.session_state.get(f"_group_send_{key_base}"):
        return
    # 新一轮发送清除上一轮的错误提示（错误不进历史，只保留到下一次发送）
    st.session_state.pop(f"_send_error_{key_base}", None)
    input_key = f"chat_input_{key_base}"
    st.session_state[f"_pending_send_{key_base}"] = st.session_state.get(input_key, "")
    st.session_state[input_key] = ""


def _render_emoji_panel(input_key):
    """在 st.popover 内渲染 emoji 网格，点击追加到对应输入框"""
    cols = st.columns(8)
    for i, emoji in enumerate(EMOJIS):
        cols[i % 8].button(emoji, key=f"emoji_{input_key}_{i}",
                           use_container_width=True, help=emoji,
                           on_click=_append_emoji, args=(emoji, input_key))


def _wait_tts_done(member_id, content):
    """等待某成员一条回复的语音生成完成（请求 /api/tts-audio，响应到达 = 合成完毕）。

    在 audio 元素渲染前预热：合成结果写入后端缓存，fragment rerun 渲染 audio 时
    src 命中缓存秒回、立即可播。timeout 90s：覆盖正常合成（2-40s，含权重切换重载），
    TTS 服务挂掉/极慢时快速放弃不拖死文字流程（TTS 失败不阻断聊天）。
    """
    try:
        requests.get(
            f"{BACKEND_URL}/api/tts-audio",
            params={"character_id": member_id, "text": content},
            timeout=90,
        )
    except Exception:
        pass


def _group_step(key_base, state):
    """群聊分步发送：一次 fragment 执行只生成一个成员的回复。

    语音开启时，等该成员 TTS 生成完成后才推进到下一个成员（rerun 后再生成）——
    「第一个人的语音生成完成后第二个人再开始回复」。
    state = {"message": 老师消息, "history": 发送前历史, "idx": 当前成员下标,
             "members": 本轮回复顺序（点名检测重排后的成员列表）}
    """
    members = state.get("members") or group_members(key_base)
    idx = state["idx"]
    member_id = members[idx]
    messages = get_current_messages(key_base, "group")
    # 历史给后端：发送前历史 + 之前成员已生成的回复（user 消息由 message 参数提供）
    prev_replies = [
        {"role": m["role"], "content": m["content"]}
        for m in messages[len(state["history"]) + 1:]
    ]
    history_for_backend = state["history"] + prev_replies
    ok, replies, err = send_group_message(state["message"], history_for_backend, [member_id])
    if not ok:
        # 请求级失败（超时/后端不可达）：终止本轮分步状态机，错误只显示不进历史
        del st.session_state[f"_group_send_{key_base}"]
        st.session_state[f"_send_error_{key_base}"] = err
        st.rerun(scope="fragment")

    r = replies[0] if replies else None
    member_ok = bool(r and r.get("ok", True))
    if member_ok:
        messages.append({"role": r["role"], "content": r["content"]})
    else:
        # 单成员生成失败：错误只显示，不写聊天历史（也就不会进 prev_replies/
        # 后续成员上下文），不阻断后面成员的生成
        st.session_state[f"_send_error_{key_base}"] = (r or {}).get("content", "生成失败")

    # 语音开启时：等该成员这条回复的 TTS 生成完成才轮到下一个成员
    # （失败成员没有正文可合成，跳过等待直接推进）
    if member_ok and st.session_state.voice_enabled and st.session_state.tts_up:
        cur_char = next(
            (c for c in (load_characters_cache() or []) if c["id"] == member_id), {}
        )
        if cur_char.get("has_tts"):
            _wait_tts_done(member_id, r["content"])

    state["idx"] = idx + 1
    if state["idx"] >= len(members):
        del st.session_state[f"_group_send_{key_base}"]
    st.rerun(scope="fragment")


def _do_send(prompt, key_base, mode="single"):
    """实际发送：调用后端并更新会话历史（不含 spinner 与 rerun）。

    单聊：一条用户消息 + 一条 assistant 回复，存 conversations[key_base]；
    群聊：初始化分步状态机（_group_send_{key_base}），由 fragment 逐步执行——
    每步只生成一个成员回复，语音开启时等该成员 TTS 完成再轮到下一个，
    消息逐步显示；存 group_conversations[key_base]，与单聊完全隔离。
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return

    messages = get_current_messages(key_base, mode)
    messages.append({"role": "user", "content": prompt})

    if mode == "group":
        # 本轮回复顺序：明确点名角色时该角色优先（称呼首次出现位置排序，
        # 未点名保持默认顺序）——只改顺序，不改最多两条回复的规则
        ordered = detect_mention_order(prompt, group_members(key_base), load_characters_cache() or [])
        st.session_state[f"_group_send_{key_base}"] = {
            "message": prompt,
            "history": messages[:-1],
            "idx": 0,
            "members": ordered,
        }
        return

    # 历史给后端时不包含刚加的这条用户消息
    history_for_backend = messages[:-1]
    ok, reply_or_err = send_chat_message(prompt, history_for_backend, key_base)
    if ok:
        messages.append({"role": "assistant", "content": reply_or_err})
    else:
        # 失败/超时：错误只显示在 UI，不作为 assistant 回复写入聊天历史
        # （messages 是 session 列表的引用，user 消息保留，assistant 不追加）
        st.session_state[f"_send_error_{key_base}"] = reply_or_err
    st.session_state.conversations[key_base] = messages


def _toggle_voice():
    """语音开关翻转（on_click 回调：在 rerun 渲染前执行，
    因此同一次 fragment rerun 内按钮图标与音频同步更新，无需二次 rerun）"""
    st.session_state.voice_enabled = not st.session_state.voice_enabled


@st.fragment
def render_chat_fragment(key_base, name, mode="single"):
    """聊天交互区（消息历史 + emoji + 输入框 + 发送 + 回复状态）。

    mode="single"：单聊，key_base=角色id，消息 role 为 user/assistant；
    mode="group"：群聊，key_base=群id，消息 role 为 user/角色id，
    渲染时按角色显示头像与名字标签，共享群历史与单聊完全隔离。

    用 @st.fragment 隔离：点击本区域内的 widget（emoji、输入框、发送）只触发
    fragment rerun，fragment 外的角色信息 / 立绘 / 校园背景不参与 rerun。
    """
    # 取出待发送消息（延迟到渲染之后再执行，让"正在回复中"提示显示在消息区内部，
    # 避免独立 spinner 元素占高度导致页面跳动）
    pending = st.session_state.pop(f"_pending_send_{key_base}", None)

    # 探测 GPT-SoVITS 是否在线（放在 fragment 内 + 5 秒短缓存：刚启动时 9880
    # 未就绪导致 tts_up=False 被 60 秒锁死、fragment rerun 又不重查，是
    # 「发消息无语音、必须刷新才有」的根因；5 秒短缓存让它最多 5 秒后发消息
    # 即自动恢复，无需刷新整页；本地探测 ~3ms，短缓存也避免 9880 异常时
    # 每次发消息都等 3 秒超时）
    now = time.time()
    if now - st.session_state.tts_checked_at > 5:
        try:
            r = requests.get(f"{BACKEND_URL}/api/tts/status", timeout=3)
            st.session_state.tts_up = bool(r.json().get("tts_available"))
        except Exception:
            st.session_state.tts_up = False
        st.session_state.tts_checked_at = now

    # ---- 语音开关（必须在 fragment 内：点击只触发 fragment 局部 rerun，
    # fragment 外的立绘/角色信息/背景零重绘不闪烁；状态翻转走 on_click
    # 回调（渲染前执行），同一次 rerun 内图标与音频同步更新，无需二次 rerun）----
    _t1, _t2 = st.columns([0.9, 0.1])
    with _t2:
        st.button(
            "🔊" if st.session_state.voice_enabled else "🔇",
            key=f"voice_toggle_{key_base}",
            help="语音开关：开启时新回复自动播放角色日语语音",
            on_click=_toggle_voice,
        )

    # ---- 消息区 ----
    messages = get_current_messages(key_base, mode)
    characters = load_characters_cache() or []
    char_map = {c["id"]: c for c in characters}
    # 音频由 <audio src=后端> 浏览器后台拉取，fragment 本身不做任何网络等待；
    # 每条消息按自己的角色独立判断 has_tts（群聊内不同角色音色不同）
    voice_on = st.session_state.voice_enabled and st.session_state.tts_up
    last_ai_idx = max(
        (i for i, m in enumerate(messages) if m["role"] != "user"), default=-1
    )
    rows = []
    for i, msg in enumerate(messages):
        content = msg["content"].replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        if msg["role"] == "user":
            avatar = get_user_avatar_html()
            rows.append(
                f'<div class="chat-row user">'
                f'<div class="chat-avatar">{avatar}</div>'
                f'<div class="bubble">{content}</div></div>'
            )
        else:
            # 单聊 role 恒为 assistant → key_base 即角色；群聊 role 即角色id
            speaker_id = msg["role"] if mode == "group" else key_base
            speaker = char_map.get(speaker_id, {})
            speaker_name = speaker.get("name", speaker_id)
            avatar = get_character_avatar_html(speaker_id)
            # 群聊：气泡内加角色名字标签（主题色），明确是谁在说话
            name_tag = ""
            if mode == "group":
                accent = speaker.get("color") or "#FF6B9D"
                name_tag = f'<div class="bubble-name" style="color:{accent};">[{speaker_name}]</div>'
            # 语音：仅最新一条 AI 回复自动播放（记入 played 防重绘重播），旧消息手动点播
            audio_html = ""
            if voice_on and speaker.get("has_tts"):
                akey = f"{key_base}:{speaker_id}:{i}"
                autoplay = i == last_ai_idx and akey not in st.session_state.played_audio_keys
                if autoplay:
                    st.session_state.played_audio_keys.add(akey)
                src = (
                    f"{BACKEND_URL}/api/tts-audio"
                    f"?character_id={speaker_id}&text={quote(msg['content'])}"
                )
                audio_html = (
                    f'<audio class="bubble-audio" controls'
                    f' preload="{"auto" if autoplay else "none"}"'
                    + (" autoplay" if autoplay else "")
                    + f' src="{src}"></audio>'
                )
            rows.append(
                f'<div class="chat-row assistant">'
                f'<div class="chat-avatar">{avatar}</div>'
                f'<div class="bubble">{name_tag}{content}{audio_html}</div></div>'
            )
    # 正在回复：作为消息区内部的一条提示（不占额外高度，避免页面跳动）
    # 群聊分步：首轮显示第一个成员名，后续轮显示状态机当前成员名
    reply_hint = None
    if pending:
        if mode == "group":
            _gstate = st.session_state.get(f"_group_send_{key_base}") or {}
            _members = _gstate.get("members") or group_members(key_base)
            reply_hint = (
                char_map.get(_members[0], {}).get("name", _members[0])
                if _members else name
            )
        else:
            reply_hint = name
    else:
        _gstate = st.session_state.get(f"_group_send_{key_base}")
        if _gstate and mode == "group":
            _members = _gstate.get("members") or group_members(key_base)
            _idx = _gstate["idx"]
            if _idx < len(_members):
                reply_hint = char_map.get(_members[_idx], {}).get("name", _members[_idx])
    if reply_hint:
        if mode == "group":
            # 群聊分步生成：提示不绑单一头像
            rows.append(
                f'<div class="chat-row assistant">'
                f'<div class="bubble replying">✨ {reply_hint} 正在回复中...</div></div>'
            )
        else:
            avatar = get_character_avatar_html(key_base)
            rows.append(
                f'<div class="chat-row assistant">'
                f'<div class="chat-avatar">{avatar}</div>'
                f'<div class="bubble replying">✨ {reply_hint}正在回复中...</div></div>'
            )
    # 发送失败/超时提示：仅 UI 展示（session_state 暂存，下次发送清除），
    # 不进入 messages 聊天历史，也不会作为上下文发给模型
    send_err = st.session_state.get(f"_send_error_{key_base}")
    if send_err:
        err_html = (str(send_err).replace("<", "&lt;")
                    .replace(">", "&gt;").replace("\n", "<br>"))
        rows.append(
            '<div class="chat-row assistant">'
            f'<div class="bubble" style="background:#FDEDEC;color:#C0392B;'
            f'align-self:flex-start;">❌ {err_html}</div></div>'
        )
    if not rows:
        if mode == "group":
            body = (
                f'<div class="welcome-title">「{name}」群聊</div>'
                '<div class="welcome-sub">发出第一条消息吧～两位都会回复你</div>'
            )
        else:
            # 空对话的欢迎语：优先角色 greeting（character.json），否则通用兜底（与主页 Hero 一致）
            cur = char_map.get(key_base, {})
            greeting = (cur.get("greeting") or "").strip()
            if greeting:
                body = f'<div class="welcome-title">{greeting}</div>'
            else:
                body = (
                    f'<div class="welcome-title">你好呀，我是{name}～</div>'
                    '<div class="welcome-sub">今天想和我聊点什么？</div>'
                )
        welcome_html = (
            '<div class="chat-messages" style="display:flex;align-items:center;justify-content:center;">'
            '<div class="welcome-box">'
            '<div class="welcome-emoji">👋</div>'
            f'{body}'
            '</div></div>'
        )
        st.markdown(welcome_html, unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="chat-messages">{"".join(rows)}</div>', unsafe_allow_html=True)

    # ---- 输入区（方案B：输入框 + 右侧表情按钮 + 发送按钮，回车不可用）----
    input_key = f"chat_input_{key_base}"
    st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([11, 2, 3])
    with c1:
        st.text_input(
            "消息",
            key=input_key,
            label_visibility="collapsed",
            placeholder=(f"在「{name}」群里发消息..." if mode == "group" else f"给 {name} 发消息..."),
        )
    with c2:
        with st.popover("😀", use_container_width=True):
            _render_emoji_panel(input_key)
    with c3:
        st.button("发送", key=f"send_{key_base}",
                  type="primary", use_container_width=True,
                  on_click=_prepare_send, args=(key_base, mode))

    # 渲染完成后执行发送（阻塞期间"正在回复中"提示显示在消息区内部，不占额外高度）
    if pending:
        _do_send(pending, key_base, mode)
        st.rerun(scope="fragment")
    else:
        # 群聊分步状态机：每轮 fragment 只生成一个成员，语音开启时等该成员
        # TTS 生成完成才推进（_group_step 内 rerun），消息逐步显示
        _gstate = st.session_state.get(f"_group_send_{key_base}")
        if _gstate:
            _group_step(key_base, _gstate)


def render_chat_page_styles():
    """聊天/群聊页共用样式：语音开关隐藏 + 槽位 + 气泡播放器 + 群聊名字标签"""
    st.markdown(
        '<style>'
        '[class*="st-key-voice_toggle_"] { display:none !important; }'
        '.character-info .ci-actions span.voice-slot { display:inline-block; width:36px; height:24px; }'
        '[data-testid="stElementContainer"]:has(iframe[srcdoc*="voice-btn"]) {'
        'visibility:hidden; height:0 !important; min-height:0 !important;'
        'margin:0 !important; padding:0 !important; }'
        '.bubble-audio { display:block;width:230px;height:34px;margin:6px 0 0;border-radius:10px; }'
        '.bubble-name { font-size:12px; font-weight:700; margin-bottom:2px; }'
        '</style>',
        unsafe_allow_html=True,
    )


def render_character_info_bar(title, status):
    """角色信息条（标题 + 状态 + 日历/♡/语音开关）——单聊页与群聊页共用。

    🔊 语音开关：iframe 按钮模拟点击 fragment 内真实按钮（只触发 fragment
    rerun，立绘/背景零重绘不闪烁），图标经 500ms 轮询同步。
    📅 日历入口：面板展开/月份切换全部纯前端 JS，零 Streamlit rerun，
    聊天区/立绘/背景零重绘；今天数据由 Python 动态生成。
    """
    now = datetime.now().astimezone()
    weekday_cn = "星期" + "一二三四五六日"[now.weekday()]
    h = now.hour
    period = ("清晨" if 5 <= h <= 8 else "上午" if 9 <= h <= 11 else "中午"
              if 12 <= h <= 13 else "下午" if 14 <= h <= 17 else
              "晚上" if 18 <= h <= 21 else "深夜")
    today_info = f"{now.month}月{now.day}日 · {weekday_cn}"
    today_time = f"{period} · {now.strftime('%H:%M')}"
    # innerHTML 里的 <script> 和内联事件（onerror）都会被 Streamlit 前端拦截
    # （st.markdown / st.html 均无效，实测确认），唯一可行路径是
    # components.html（iframe）：iframe 内 JS 能执行，且 srcdoc 与父页同源，
    # 可通过 window.parent.document 操作外页面板（开合/月份切换），零 rerun
    cal_js = (
        'var T={y:' + str(now.year) + ',m:' + str(now.month) + ',d:' + str(now.day) + '};'
        'var view={y:T.y,m:T.m};'
        'var P=window.parent.document;'
        'var panel=P.getElementById("cal-panel");'
        'var btn=document.getElementById("cal-btn");'
        'if(!panel||!btn)return;'
        'function render(){'
        'P.getElementById("cal-title").textContent="🌸 "+view.y+"年"+view.m+"月";'
        'var first=new Date(view.y,view.m-1,1),startWd=first.getDay();'
        'var days=new Date(view.y,view.m,0).getDate(),prevDays=new Date(view.y,view.m-1,0).getDate();'
        'var html="";'
        'for(var i=startWd-1;i>=0;i--)html+=\'<span class="cal-day cal-dim">\'+(prevDays-i)+\'</span>\';'
        'for(var d=1;d<=days;d++){'
        'var wd=new Date(view.y,view.m-1,d).getDay();'
        'var cls="cal-day"+(wd===0?" cal-sun":"")+(wd===6?" cal-sat":"");'
        'if(d===T.d&&view.m===T.m&&view.y===T.y)cls+=" cal-today";'
        'html+=\'<span class="\'+cls+\'">\'+d+\'</span>\';'
        '}'
        'var tail=(7-(startWd+days)%7)%7;'
        'for(var n=1;n<=tail;n++)html+=\'<span class="cal-day cal-dim">\'+n+\'</span>\';'
        'P.getElementById("cal-grid").innerHTML=html;'
        '}'
        'var cont=null;'
        'try{cont=window.frameElement;}catch(e){}'
        'while(cont&&!(cont.getAttribute&&cont.getAttribute("data-testid")==="stElementContainer"))cont=cont.parentElement;'
        'function place(){'
        'var slot=P.getElementById("cal-slot");'
        'if(!cont||!slot)return;'
        'var r=slot.getBoundingClientRect();'
        'cont.style.setProperty("position","fixed","important");'
        'cont.style.setProperty("left",(r.left+r.width/2-18)+"px","important");'
        'cont.style.setProperty("top",(r.top+r.height/2-18)+"px","important");'
        'cont.style.setProperty("width","36px","important");'
        'cont.style.setProperty("height","36px","important");'
        'cont.style.setProperty("z-index","130","important");'
        'cont.style.setProperty("visibility","visible","important");'
        '}'
        'btn.onclick=function(e){e.stopPropagation();var p=P.getElementById("cal-panel");if(p)p.classList.toggle("cal-open");};'
        'P.addEventListener("click",function(e){'
        'var t=e.target;'
        'if(t&&t.id==="cal-prev"){e.stopPropagation();view.m--;if(view.m<1){view.m=12;view.y--;}render();}'
        'else if(t&&t.id==="cal-next"){e.stopPropagation();view.m++;if(view.m>12){view.m=1;view.y++;}render();}'
        'else if(!(btn.contains(t))&&!(t.closest&&t.closest(".cal-panel"))){var p=P.getElementById("cal-panel");if(p)p.classList.remove("cal-open");}'
        '});'
        'P.defaultView.addEventListener("resize",place);'
        'requestAnimationFrame(function(){requestAnimationFrame(place);});'
        'setTimeout(place,300);setTimeout(place,1000);'
        'render();'

    )
    cal_iframe = (
        '<!DOCTYPE html><html><head><style>'
        'html,body{margin:0;padding:0;background:transparent;overflow:hidden;}'
        '#cal-btn{width:36px;height:36px;display:flex;align-items:center;justify-content:center;'
        'font-size:17px;cursor:pointer;opacity:0.8;user-select:none;'
        'transition:opacity 0.2s,transform 0.2s;}'
        '#cal-btn:hover{opacity:1;transform:scale(1.12);}'
        '</style></head><body>'
        '<div id="cal-btn" title="日历">📅</div>'
        '<script>(function(){' + cal_js + '}());</script>'
        '</body></html>'
    )
    st.markdown(
        '<div class="character-info">'
        + '<div class="ci-left">'
        + f'<span class="ci-name">{title}</span>'
        + f'<span class="ci-status">{status}</span>'
        + '</div>'
        + '<div class="ci-actions">'
        + '<span class="cal-slot" id="cal-slot" title="日历"></span>'
        + '<span title="好感度（预留）">♡</span>'
        + '<span class="voice-slot" id="voice-slot" title="语音开关"></span>'
        + '</div>'
        + '<div class="cal-panel" id="cal-panel">'
        + '<div class="cal-head">'
        + '<span class="cal-nav" id="cal-prev">‹</span>'
        + '<span class="cal-title" id="cal-title"></span>'
        + '<span class="cal-nav" id="cal-next">›</span>'
        + '</div>'
        + '<div class="cal-week"><span>日</span><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span></div>'
        + '<div class="cal-grid" id="cal-grid"></div>'
        + f'<div class="cal-foot"><div class="cal-today-label">✦ 今天</div><div class="cal-today-info">{today_info}</div><div class="cal-today-time">{today_time}</div></div>'
        + '</div>'
        + '</div>',
        unsafe_allow_html=True,
    )
    # 日历按钮 iframe：36×36，CSS 默认隐藏（不占文档流），由 iframe 内 JS
    # 计算外页 cal-slot 位置后精确定位并显示——面板开合/月份切换零 rerun
    components.html(cal_iframe, width=36, height=36, scrolling=False)
    # 🔊 语音开关 iframe（信息行最右）：点击模拟点击 fragment 内真实
    # st.button（只触发 fragment rerun）；图标经 500ms 轮询读真实按钮文本同步
    voice_js = (
        'var P=window.parent.document;'
        'var btn=document.getElementById("voice-btn");'
        'var realBtn=function(){return P.querySelector(\'[class*="st-key-voice_toggle_"] button\');};'
        'if(!btn)return;'
        'var cont=null;'
        'try{cont=window.frameElement;}catch(e){}'
        'while(cont&&!(cont.getAttribute&&cont.getAttribute("data-testid")==="stElementContainer"))cont=cont.parentElement;'
        'function place(){'
        'var slot=P.getElementById("voice-slot");'
        'if(!cont||!slot)return;'
        'var r=slot.getBoundingClientRect();'
        'cont.style.setProperty("position","fixed","important");'
        'cont.style.setProperty("left",(r.left+r.width/2-18)+"px","important");'
        'cont.style.setProperty("top",(r.top+r.height/2-18)+"px","important");'
        'cont.style.setProperty("width","36px","important");'
        'cont.style.setProperty("height","36px","important");'
        'cont.style.setProperty("z-index","130","important");'
        'cont.style.setProperty("visibility","visible","important");'
        '}'
        'function sync(){'
        'var rb=realBtn();'
        'if(!rb)return;'
        'var want=rb.textContent.indexOf("🔊")>=0?"🔊":"🔇";'
        'if(btn.textContent!==want)btn.textContent=want;'
        '}'
        'btn.onclick=function(e){e.stopPropagation();var rb=realBtn();if(rb)rb.click();};'
        'P.defaultView.addEventListener("resize",place);'
        'requestAnimationFrame(function(){requestAnimationFrame(place);});'
        'setTimeout(place,300);setTimeout(place,1000);'
        'setInterval(sync,500);'
        'sync();'
    )
    voice_iframe = (
        '<!DOCTYPE html><html><head><style>'
        'html,body{margin:0;padding:0;background:transparent;overflow:hidden;}'
        '#voice-btn{width:36px;height:36px;display:flex;align-items:center;justify-content:center;'
        'font-size:20px;cursor:pointer;opacity:0.8;user-select:none;'
        'transition:opacity 0.2s,transform 0.2s;}'
        '#voice-btn:hover{opacity:1;transform:scale(1.12);}'
        '</style></head><body>'
        '<div id="voice-btn" title="语音开关：开启时新回复自动播放角色日语语音">🔊</div>'
        '<script>(function(){' + voice_js + '}());</script>'
        '</body></html>'
    )
    components.html(voice_iframe, width=36, height=36, scrolling=False)


def render_stage_and_background(character_id, name):
    """立绘舞台 + 全局背景图——单聊页与群聊页共用（群聊显示第一成员立绘）"""
    portrait = get_character_portrait(character_id)
    bg = get_background(character_id)
    # 背景图铺满整个主视图（fixed img + 让 .main 提升层级并透明，透出背景图）
    if bg:
        st.markdown(f'<img src="{bg}" class="global-background" alt="">', unsafe_allow_html=True)
        st.markdown(
            '<style>'
            '[data-testid="stAppViewContainer"] { background: transparent !important; }'
            '[data-testid="stMain"] { position: relative !important; z-index: 1 !important; background: transparent !important; }'
            '</style>',
            unsafe_allow_html=True,
        )
    if portrait:
        img_tag = f'<img src="{portrait}" alt="{name}">'
    else:
        avatar_url = f"{BACKEND_URL}/api/characters/{character_id}/avatar"
        img_tag = f'<img src="{avatar_url}" alt="{name}" style="border-radius:24px;">'
    stage_html = (
        '<div class="character-stage">'
        + '<div class="background-overlay"></div>'
        + '<div class="character-container"><div class="character-image">' + img_tag + '</div></div>'
        + '<div class="character-status"><span class="dot"></span>在线</div>'
        + '</div>'
    )
    st.markdown(stage_html, unsafe_allow_html=True)


def render_chat_page(character_id):
    """渲染聊天页：左侧角色立绘 + 右侧聊天 fragment"""
    characters = load_characters_cache()

    current_char = next((c for c in characters if c["id"] == character_id), None)
    if not current_char:
        st.error(f"角色不存在: {character_id}")
        if st.button("返回主页"):
            st.session_state.current_character_id = None
            st.session_state.current_group_id = None
            st.rerun()
        return

    name = current_char["name"]
    subtitle = current_char.get("subtitle", "")

    # 两栏：左角色舞台（45%）+ 右聊天消息（55%）
    col_char, col_chat = st.columns([0.9, 1.1], gap="medium")

    with col_char:
        # 语音开关 + 气泡播放器样式（在 fragment 外，一次注入即可）
        render_chat_page_styles()
        # 角色信息（普通文档流，位于立绘舞台上方，不使用 fixed/sticky）
        render_character_info_bar(name, f"{subtitle} · 在线")
        render_stage_and_background(character_id, name)

    with col_chat:
        # 聊天交互区用 fragment 隔离：点击其内 widget（emoji/输入框/发送）只触发
        # fragment rerun；角色信息 / 立绘 / 校园背景（fragment 外）不参与 rerun，避免闪烁
        render_chat_fragment(character_id, name)


def render_group_page(group_id):
    """群聊页：左侧立绘舞台（第一成员）+ 群信息条 + 右侧群聊 fragment。

    复用单聊页的舞台/背景/信息条/聊天 fragment 结构，只换标题与消息渲染模式；
    群聊历史存 group_conversations[group_id]，与单聊完全隔离。
    """
    members = group_members(group_id)
    characters = load_characters_cache()
    char_map = {c["id"]: c for c in characters}
    group_name = group_display_name(group_id)
    lead_id = members[0] if members else ""
    lead_name = char_map.get(lead_id, {}).get("name", lead_id)

    col_char, col_chat = st.columns([0.9, 1.1], gap="medium")

    with col_char:
        render_chat_page_styles()
        render_character_info_bar(group_name, f"群聊 · {len(members)} 人在线")
        render_stage_and_background(lead_id, lead_name)

    with col_chat:
        render_chat_fragment(group_id, group_name, mode="group")


# ==================== 设置页（占位） ====================

def fetch_models():
    """拉取 Ollama 已下载模型列表 + 当前生效模型 + 预加载状态（失败返回空）"""
    try:
        r = requests.get(f"{BACKEND_URL}/api/models", timeout=8)
        if r.status_code == 200:
            d = r.json()
            return d.get("models", []), d.get("current"), d.get("preload") or {}
    except Exception:
        pass
    return [], None, {}


def render_settings_page():
    """设置页：模型切换（自动检测 Ollama 已下载模型，前端一键切换）"""
    st.markdown("""
    <div style="text-align:center; padding:40px 20px 10px 20px;">
        <h1 style="color:#FF6B9D; font-size:32px;">⚙️ 设置</h1>
    </div>
    """, unsafe_allow_html=True)

    models, current, preload = fetch_models()
    st.markdown(
        f'<div style="color:#718096;font-size:14px;margin:0 0 6px 2px;">当前生效模型：<b style="color:#FF6B9D;">{current or "各角色默认（character.json）"}</b>'
        f'　<span style="font-size:12px;">（切换后持久保存，重启后端自动恢复并预加载）</span></div>',
        unsafe_allow_html=True,
    )
    # 模型预加载状态（进入设置页时拉取快照；加载中可稍后重进查看）
    pl_model = preload.get("model")
    if pl_model:
        pl_status = preload.get("status")
        if pl_status == "ok":
            pl_html = (f'模型预加载：<b style="color:#52C41A;">已就绪</b>'
                       f'（{pl_model} 常驻内存，首次对话无需等待加载）')
        elif pl_status == "loading":
            pl_html = (f'模型预加载：<b style="color:#E6A23C;">后台加载中…</b>'
                       f'（{pl_model}，冷启动约 2~3 分钟，完成后首次对话秒回）')
        elif pl_status == "failed":
            pl_html = (f'模型预加载：<b style="color:#F56C6C;">失败</b>'
                       f'（{pl_model}：{preload.get("detail", "未知原因")}，'
                       f'请确认 Ollama 正常且该模型已下载）')
        else:
            pl_html = f'模型预加载：{pl_status}（{pl_model}）'
        st.markdown(
            f'<div style="color:#718096;font-size:13px;margin:0 0 6px 2px;">{pl_html}</div>',
            unsafe_allow_html=True,
        )
    if not models:
        st.warning("⚠️ 无法获取 Ollama 模型列表——请确认 Ollama 已启动且已下载模型。")
        st.info("📋 未来计划支持：\n- Temperature/Max Tokens 调节\n- 对话历史导出\n- 主题切换")
        return

    _all_opts = ["（使用各角色默认）"] + models
    if "model_pick" not in st.session_state:
        st.session_state.model_pick = current if current in models else "（使用各角色默认）"
    pick = st.selectbox("模型切换", options=_all_opts, key="model_pick",
                        label_visibility="visible")
    if st.button("切换到该模型", type="primary", use_container_width=True):
        if pick == "（使用各角色默认）":
            requests.post(f"{BACKEND_URL}/api/model", json={"model": ""}, timeout=10)
            st.success("已恢复各角色默认模型")
        else:
            try:
                r = requests.post(f"{BACKEND_URL}/api/model", json={"model": pick}, timeout=10)
                if r.status_code == 200:
                    st.success(f"已切换到 {pick}，正在后台预加载（冷启动约 2~3 分钟，期间对话可能较慢）")
                else:
                    st.error(f"切换失败：{r.status_code}")
            except Exception as e:
                st.error(f"切换失败：{e}")

    st.markdown('<div style="height:14px;"></div>', unsafe_allow_html=True)
    st.info("📋 未来计划支持：\n- Temperature/Max Tokens 调节\n- 对话历史导出\n- 主题切换")


# ==================== 主程序入口 ====================

def main():
    # set_page_config 必须是第一个 Streamlit 命令
    st.set_page_config(
        page_title="聊天大厅",
        page_icon="💬",
        layout="wide",
        initial_sidebar_state="expanded",  # 默认展开侧边栏
    )

    init_session_state()

    # CSS 样式（日系浅色主题）
    st.markdown("""
    <style>
        /* ==== 设计变量 ==== */
        :root {
            --bg: #ECE2F3;
            --bg-top: #F4EDF8;
            --bg-bottom: #E8D9F2;
            --surface: #FFFFFF;
            --surface-solid: #FFFFFF;
            --surface-ghost: rgba(255, 255, 255, 0.55);
            --primary: #E46893;
            --primary-soft: #F9E3EC;
            --primary-deep: #D25580;
            --accent-lavender: #B9A6DE;
            --accent-sky: #A8C4E4;
            --text-main: #4A4A6A;
            --text-sub: #8A8490;
            --line: rgba(120, 90, 130, 0.12);
            --shadow-soft: 0 10px 34px rgba(120, 90, 130, 0.10);
            --shadow-hover: 0 14px 40px rgba(120, 90, 130, 0.16);
            --ok: #52C41A;
        }

        * {
            font-family: 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Segoe UI', 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji', sans-serif !important;
        }

        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header[data-testid="stHeader"] { display: none !important; }
        [data-testid="stToolbar"] { display: none !important; }
        [data-testid="stSidebarCollapseButton"] { display: none !important; }

        /* ==== 主背景（去掉 html/body 白底，紫粉渐变铺满主内容区） ==== */
        html, body {
            background: transparent !important;
        }
        [data-testid="stMain"] {
            background: linear-gradient(180deg, var(--bg-top) 0%, var(--bg) 50%, var(--bg-bottom) 100%) !important;
        }
        /* 撑满全宽：突破 Streamlit 默认 max-width，消除两侧留白 */
        [data-testid="stAppViewContainer"] .block-container {
            max-width: 100% !important;
            padding-left: 1.5rem !important;
            padding-right: 1.5rem !important;
            padding-top: 24px !important;
            padding-bottom: 16px !important;
        }
        /* 全局背景层（fixed img 铺满视口，位于内容之后） */
        .global-background {
            position: fixed;
            top: 0; left: 0;
            width: 100vw;
            height: 100vh;
            object-fit: cover !important;
            z-index: -1;
            pointer-events: none;
            filter: saturate(0.55) brightness(1.15) contrast(0.9);
        }

        /* ==== 侧边栏（半透明浅紫 · 角色陪伴应用风格） ==== */
        [data-testid="stSidebar"] {
            background: rgba(245, 240, 250, 0.82) !important;
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border-right: 1px solid var(--line) !important;
        }
        /* 高度链（flex 全链）：stSidebarContent 改 flex 列，内容区占满除 header 外的剩余高度，
           .sb-spacer 才能把底部导航压到 Sidebar 底部。
           DOM：stSidebarContent > (stSidebarHeader + stSidebarUserContent > div > stVerticalBlock)，
           而 .sb-spacer 是 st.markdown 输出，外面还包着多层盒（见下方 contents 清单）——
           用 display:contents 把它们从布局中穿透掉，spacer 才能成为 stVerticalBlock 的直接 flex 子项 */
        [data-testid="stSidebarContent"] { display: flex; flex-direction: column; }
        /* padding-bottom：Streamlit 默认给滚动留的 6rem(96px) 底部留白，压到 16px 让导航贴底 */
        [data-testid="stSidebarUserContent"] { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; padding-bottom: 16px !important; }
        [data-testid="stSidebarUserContent"] > div { flex: 1 1 auto; display: flex; flex-direction: column; }
        [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] { flex: 1 1 auto; }
        /* st.markdown 的四层包裹盒（stElementContainer > stMarkdown > 排版div > stMarkdownContainer）
           全部穿透，.sb-spacer 成为 stVerticalBlock 的直接 flex 子项后才能弹性撑开。
           注意：不能用嵌套 :has()（Chrome 不支持，且会令整条规则失效），最后一层用
           「stMarkdown 的直接子 div，且内部含有 .sb-spacer」的单层 :has() 写法 */
        [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.sb-spacer),
        [data-testid="stSidebar"] [data-testid="stMarkdown"]:has(.sb-spacer),
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"]:has(.sb-spacer),
        [data-testid="stSidebar"] [data-testid="stMarkdown"] > div:has([data-testid="stMarkdownContainer"] .sb-spacer) { display: contents; }
        .sb-spacer { flex: 1 1 0; min-height: 24px; }

        /* 品牌区（轻盈，无卡片背景） */
        .sb-brand { padding: 10px 6px 14px 6px; border-bottom: 1px solid rgba(90, 65, 90, 0.08); }
        .sb-brand-title { font-size: 18px; font-weight: 800; color: #E46893; letter-spacing: 0.5px; }
        .sb-brand-sub { font-size: 11px; color: #A99BB0; margin-top: 3px; letter-spacing: 1px; }

        /* 「角色」小节标题：保留可折叠按钮，只做轻量化（逻辑见 _render_sidebar_section）。
           加 [data-testid="stSidebar"] 前缀确保压过下方通用按钮兜底规则（特异性更高） */
        [data-testid="stSidebar"] .st-key-section_characters button {
            background: transparent !important;
            border: none !important; box-shadow: none !important;
            font-size: 12px !important; font-weight: 700 !important;
            color: #A99BB0 !important; letter-spacing: 3px;
            padding: 12px 6px 6px 6px !important;
            min-height: 0 !important; height: auto !important;
        }
        [data-testid="stSidebar"] .st-key-section_characters button:hover {
            background: transparent !important; color: #8E7F96 !important;
        }

        /* 通用按钮兜底（重新加载等）；注意 hover 只动 background-color，
           不能写 background 简写——否则会把角色按钮上的头像 background-image 一并清掉 */
        [data-testid="stSidebar"] button {
            text-align: left !important;
            justify-content: flex-start !important;
            font-size: 14px !important;
            border: none !important;
        }
        [data-testid="stSidebar"] button:hover {
            background-color: rgba(255, 255, 255, 0.7) !important;
        }

        /* 选中角色行（HTML 渲染）：头像 + 名字 + 在线 + 主题色轻盈高亮 */
        .sb-char {
            display: flex; align-items: center; gap: 10px;
            padding: 7px 10px; margin: 3px 0;
            border-radius: 12px;
            border-left: 3px solid transparent;
        }
        .sb-char-active { box-shadow: 0 4px 14px rgba(120, 90, 130, 0.10); }
        .sb-avatar {
            width: 36px; height: 36px; border-radius: 50%;
            object-fit: cover; flex: 0 0 36px;
            background: #fff;
        }
        .sb-avatar-fallback {
            display: flex; align-items: center; justify-content: center;
            color: #fff; font-size: 16px; font-weight: 700;
        }
        .sb-name { font-size: 14px; font-weight: 800; color: var(--text-main); }
        .sb-status {
            font-size: 11px; color: var(--text-sub);
            display: flex; align-items: center; gap: 5px; margin-top: 2px;
        }
        .sb-status .dot {
            width: 6px; height: 6px; border-radius: 50%;
            background: var(--ok); box-shadow: 0 0 0 2px rgba(82, 196, 26, 0.15);
        }

        /* 添加角色（纯视觉入口） + 更多功能（次级弱化） */
        .sb-add, .sb-more-row {
            font-size: 12px; color: #B3A8BA;
            padding: 5px 10px; margin: 1px 0; border-radius: 8px;
            display: flex; align-items: center; justify-content: space-between;
        }
        .sb-more-title { font-size: 11px; color: #C0B6C7; letter-spacing: 3px; margin: 16px 6px 2px 6px; }
        .sb-soon { font-size: 10px; color: #C9BFD0; }

        /* 侧边栏群聊入口按钮（成员行风格；key 随群数动态，用模糊匹配） */
        [data-testid="stSidebar"] [class*="st-key-nav_group_"] button {
            background: transparent !important;
            border: none !important; box-shadow: none !important;
            border-left: 3px solid transparent !important;
            border-radius: 12px !important;
            min-height: 44px !important;
            display: flex !important; align-items: center !important;
            font-size: 13.5px !important; font-weight: 600 !important;
            color: var(--text-main) !important;
            transition: background-color 0.15s ease, color 0.15s ease !important;
        }
        [data-testid="stSidebar"] [class*="st-key-nav_group_"] button:hover {
            background: rgba(255, 255, 255, 0.7) !important;
            color: #E46893 !important;
        }

        /* 底部辅助导航（轻量小按钮，不抢角色列表的视觉重点；前缀提高特异性防被兜底规则覆盖） */
        [data-testid="stSidebar"] .st-key-nav_settings button,
        [data-testid="stSidebar"] .st-key-nav_home button {
            background: rgba(255, 255, 255, 0.55) !important;
            border: 1px solid rgba(120, 90, 130, 0.10) !important;
            box-shadow: none !important;
            font-size: 12.5px !important; font-weight: 500 !important;
            color: #6E667C !important;
            min-height: 34px !important; height: 34px !important;
            padding: 4px 12px !important; border-radius: 10px !important;
            margin-bottom: 6px !important;
            transition: background-color 0.15s ease, color 0.15s ease !important;
        }
        [data-testid="stSidebar"] .st-key-nav_settings button:hover,
        [data-testid="stSidebar"] .st-key-nav_home button:hover {
            background: rgba(255, 255, 255, 0.9) !important;
            color: #E46893 !important;
        }

        /* ==== 通用按钮 ==== */
        button[kind="primary"] {
            background: var(--primary) !important;
            color: white !important;
            border: none !important;
            border-radius: 12px !important;
        }
        button[kind="primary"]:hover {
            background: var(--primary-deep) !important;
            box-shadow: var(--shadow-hover) !important;
        }

        /* ==== 隐藏图标字体回退 ==== */
        [data-testid="stIconMaterial"] { display: none !important; }
        [data-testid="stExpander"] summary svg { display: none !important; }
        [data-testid="stExpander"] details summary { list-style: none !important; }
        [data-testid="stExpander"] details summary::-webkit-details-marker,
        [data-testid="stExpander"] details summary::marker { display: none !important; content: "" !important; }

        /* ==== 角色信息（普通文档流，位于立绘舞台上方，非 fixed/sticky） ==== */
        .character-info {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: rgba(255, 255, 255, 0.65);
            padding: 10px 16px;
            margin-bottom: 12px;
            border-radius: 16px;
            position: relative;
        }
        .character-info .ci-left { display: flex; align-items: baseline; gap: 8px; }
        .character-info .ci-name { font-size: 18px; font-weight: 700; color: var(--text-main); }
        .character-info .ci-status { font-size: 12px; color: var(--text-sub); }
        .character-info .ci-actions { display: flex; gap: 14px; align-items: center; }
        .character-info .ci-actions span {
            font-size: 16px; color: var(--text-sub); opacity: 0.5; cursor: default; transition: opacity 0.2s;
        }
        .character-info .ci-actions span:hover { opacity: 0.9; }

        /* ==== 二次元日历（小型浮动面板，纯前端交互零 rerun） ==== */
        /* 📅 按钮在 iframe 内；外层 cal-slot 仅作定位锚点占位 */
        .character-info .ci-actions span.cal-slot { display: inline-block; width: 36px; height: 24px; }
        /* 日历按钮 iframe 容器：默认隐藏且不占文档流，由 iframe 内 JS 定位后显示 */
        [data-testid="stElementContainer"]:has(iframe[srcdoc*="cal-btn"]) {
            visibility: hidden; height: 0 !important; min-height: 0 !important;
            margin: 0 !important; padding: 0 !important;
        }
        .cal-panel {
            display: none; position: absolute; top: calc(100% + 10px); right: 0;
            width: 300px; padding: 14px 16px 12px; z-index: 120;
            background: rgba(255, 255, 255, 0.88);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 107, 157, 0.18);
            border-radius: 18px;
            box-shadow: 0 14px 44px rgba(96, 66, 82, 0.16);
        }
        .cal-panel.cal-open { display: block; }
        .cal-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
        .cal-title { font-size: 15px; font-weight: 700; color: var(--text-main); }
        .cal-nav { cursor: pointer; color: #E46893; font-size: 18px; width: 26px; height: 26px; line-height: 24px; text-align: center; border-radius: 8px; }
        .cal-nav:hover { background: rgba(255, 107, 157, 0.12); }
        .cal-week { display: grid; grid-template-columns: repeat(7, 1fr); font-size: 11px; color: var(--text-sub); text-align: center; margin-bottom: 4px; }
        .cal-week span:first-child { color: #E46893; }
        .cal-week span:last-child { color: #7EC8E3; }
        .cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
        .cal-day { font-size: 12px; text-align: center; padding: 5px 0; border-radius: 9px; color: var(--text-main); }
        .cal-day.cal-sun { color: #E46893; }
        .cal-day.cal-sat { color: #7EC8E3; }
        .cal-day.cal-dim { color: rgba(120, 110, 125, 0.32); }
        .cal-day.cal-today {
            background: #FF6B9D; color: #fff; font-weight: 700;
            box-shadow: 0 3px 10px rgba(255, 107, 157, 0.35); position: relative;
        }
        .cal-day.cal-today::after { content: '✿'; position: absolute; top: -3px; right: 0px; font-size: 8px; }
        .cal-foot { margin-top: 10px; padding-top: 8px; border-top: 1px dashed rgba(255, 107, 157, 0.25); text-align: center; }
        .cal-today-label { font-size: 11px; color: #E46893; }
        .cal-today-info { font-size: 13px; font-weight: 700; color: var(--text-main); }
        .cal-today-time { font-size: 11px; color: var(--text-sub); }

        /* ==== 角色舞台（stage > 背景层 + 遮罩 + 立绘容器） ==== */
        .character-stage {
            position: relative;
            height: calc(100vh - 205px);
            min-height: 320px;
            border-radius: 24px;
            overflow: hidden;
            background: transparent;
        }
        .background-layer {
            position: absolute;
            inset: 0;
            background-size: cover;
            background-position: center;
            z-index: 0;
        }
        .background-overlay {
            position: absolute;
            inset: 0;
            z-index: 1;
            background: transparent;
        }
        .character-container {
            position: absolute;
            left: 0; right: 0; bottom: 0;
            height: 90%;
            display: flex;
            align-items: flex-end;
            justify-content: center;
            z-index: 2;
            pointer-events: none;
        }
        .character-image {
            width: 100%;
            height: 100%;
            display: flex;
            align-items: flex-end;
            justify-content: center;
        }
        .character-image img {
            max-width: 94%;
            max-height: 100%;
            object-fit: contain;
            object-position: bottom center;
            filter: drop-shadow(0 16px 34px rgba(80, 50, 80, 0.24));
        }
        .character-status {
            position: absolute;
            left: 16px; bottom: 16px;
            z-index: 3;
            padding: 5px 12px;
            border-radius: 18px;
            background: var(--surface-ghost);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            font-size: 11px;
            color: var(--text-main);
            display: flex; align-items: center; gap: 6px;
        }
        .character-status .dot {
            width: 7px; height: 7px; border-radius: 50%;
            background: var(--ok);
            box-shadow: 0 0 0 3px rgba(111, 200, 140, 0.18);
        }

        /* ==== 聊天消息区（开放、无卡片边界） ==== */
        .chat-messages {
            background: transparent;
            padding: 8px 4px;
            height: calc(100vh - 205px);
            min-height: 320px;
            max-height: none;
            overflow-y: auto;
        }
        .chat-messages::-webkit-scrollbar { width: 6px; }
        .chat-messages::-webkit-scrollbar-track { background: transparent; }
        .chat-messages::-webkit-scrollbar-thumb { background: rgba(90, 65, 80, 0.15); border-radius: 3px; }

        .chat-row { display: flex; align-items: flex-start; gap: 10px; margin: 12px 0; animation: fadeInUp 0.3s ease-out; }
        .chat-row.user { flex-direction: row-reverse; }
        .chat-avatar {
            flex-shrink: 0; width: 36px; height: 36px; border-radius: 50%;
            overflow: hidden; display: flex; align-items: center; justify-content: center;
            background: var(--surface-solid); border: 1px solid var(--line);
            box-shadow: var(--shadow-soft);
        }
        .chat-avatar img { width: 100%; height: 100%; object-fit: cover; }
        .bubble {
            max-width: 76%;
            padding: 11px 15px;
            border-radius: 16px;
            position: relative;
            word-wrap: break-word;
            white-space: pre-wrap;
            line-height: 1.65;
            font-size: 15px;
            box-shadow: 0 2px 8px rgba(96, 66, 82, 0.05);
            color: var(--text-main);
        }
        .chat-row.assistant .bubble { background: var(--surface-solid); border-bottom-left-radius: 5px; }
        .bubble.replying { color: var(--text-sub); font-style: italic; opacity: 0.85; }
        .chat-row.assistant .bubble::before {
            content: ''; position: absolute; left: -7px; bottom: 12px;
            width: 0; height: 0;
            border: 7px solid transparent;
            border-right-color: var(--surface-solid);
            border-left: 0;
        }
        .chat-row.user .bubble { background: var(--primary-soft); border-bottom-right-radius: 5px; }
        .chat-row.user .bubble::before {
            content: ''; position: absolute; right: -7px; bottom: 12px;
            width: 0; height: 0;
            border: 7px solid transparent;
            border-left-color: var(--primary-soft);
            border-right: 0;
        }

        .welcome-box {
            text-align: center;
            padding: 40px 48px;
            background: rgba(255, 255, 255, 0.6);
            border-radius: 24px;
            box-shadow: 0 8px 30px rgba(96, 66, 82, 0.06);
        }
        .welcome-box .welcome-emoji { font-size: 46px; margin-bottom: 18px; }
        .welcome-box .welcome-title { font-size: 26px; font-weight: 700; color: var(--text-main); margin-bottom: 8px; }
        .welcome-box .welcome-sub { font-size: 15px; color: var(--text-sub); }

        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* ==== 聊天大厅（Hero 式角色展示 + Carousel） ==== */
        .hall-head { padding: 2px 4px 14px 4px; }
        .hall-head-title { font-size: 22px; font-weight: 800; color: #E46893; letter-spacing: 0.5px; }
        .hall-head-sub { font-size: 13px; color: #9A93A0; margin-top: 4px; }

        /* Hero 容器：场景图 + 立绘 + 柔光由 fragment 动态注入的背景层叠加，
           这里只负责容器本身的形状。不再有白色矩形卡片。 */
        .st-key-hall_hero {
            position: relative;
            overflow: hidden;
            border-radius: 28px;
            min-height: calc(100vh - 262px);
            background-color: #F3EAF6;
            border: 1px solid rgba(255, 255, 255, 0.55);
            box-shadow: 0 18px 48px rgba(120, 90, 130, 0.16);
            /* 容器本身就是 Streamlit 的 flex 纵向块：让文字块在 Hero 内垂直居中，
               高视口下不会全堆在顶部（不是 flex 容器时该声明无害） */
            justify-content: center;
        }

        /* 文字块只占 Hero 左侧，右侧留给立绘 */
        .hall-text { padding: 0 0 0 2%; max-width: 440px; }
        /* Streamlit 自带的标题规则特异性高于类选择器，颜色必须带 !important 才能生效 */
        .hall-name {
            /* 字号也必须 !important：Streamlit 自带的 h1 规则（2.75rem = 44px）特异性更高 */
            margin: 0 !important; font-size: 38px !important; line-height: 1.15 !important;
            font-weight: 800; color: #45405C !important; letter-spacing: 1px;
            text-shadow: 0 2px 14px rgba(255, 255, 255, 0.75);
        }
        /* 名字下方的点缀：用 mask 向右渐隐，做成柔和的一笔，而不是模板式色块 */
        .hall-accent {
            display: block; width: 118px; height: 3px; border-radius: 3px;
            margin: 14px 0 16px 2px;
            -webkit-mask-image: linear-gradient(90deg, #000 0%, rgba(0, 0, 0, 0.42) 58%, transparent 100%);
            mask-image: linear-gradient(90deg, #000 0%, rgba(0, 0, 0, 0.42) 58%, transparent 100%);
        }
        .hall-sub { font-size: 15px; color: #7C7488; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
        .hall-online { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: #4FA65B; }
        .hall-online .dot {
            width: 8px; height: 8px; border-radius: 50%; background: #52C41A;
            box-shadow: 0 0 0 3px rgba(82, 196, 26, 0.16);
        }
        .hall-greeting { margin: 20px 0 26px 0; font-size: 16px; line-height: 1.75; color: #6E667C; max-width: 520px; }

        /* Hero 内的 CTA 胶囊按钮 */
        .st-key-hall_start button {
            width: auto !important; min-width: 150px;
            border-radius: 999px !important;
            padding: 13px 30px !important;
            font-size: 15px !important; font-weight: 700 !important; letter-spacing: 1px;
            box-shadow: 0 12px 26px rgba(228, 104, 147, 0.34) !important;
        }

        /* 左右切换箭头：位于 Hero 卡片外侧、与卡片垂直居中 */
        .st-key-hall_prev button, .st-key-hall_next button {
            width: 34px !important; height: 34px !important; min-height: 34px !important;
            border-radius: 50% !important; padding: 0 !important;
            margin: 0 auto !important; display: block !important;
            background: rgba(255, 255, 255, 0.92) !important;
            border: 1px solid rgba(120, 90, 130, 0.14) !important;
            box-shadow: 0 6px 16px rgba(120, 90, 130, 0.14) !important;
            transition: all 0.18s !important;
            opacity: 1 !important;
        }
        /* 字形颜色/字号要同时落在 button 与其内部 <p> 上（Streamlit 自带 p 规则会覆盖 button） */
        .st-key-hall_prev button, .st-key-hall_next button,
        .st-key-hall_prev button p, .st-key-hall_next button p {
            color: #D25580 !important;
            font-size: 17px !important; line-height: 1 !important;
        }
        .st-key-hall_prev button p, .st-key-hall_next button p { margin: 0 !important; }
        .st-key-hall_prev button:hover, .st-key-hall_next button:hover {
            background: #E46893 !important; border-color: #E46893 !important; transform: scale(1.06);
        }
        .st-key-hall_prev button:hover, .st-key-hall_next button:hover,
        .st-key-hall_prev button:hover p, .st-key-hall_next button:hover p {
            color: #FFFFFF !important;
        }
        /* 只有一个角色时箭头置灰：按钮仍然清晰可见（"这里能切换"的提示），只是明确不可点 */
        .st-key-hall_prev button:disabled, .st-key-hall_next button:disabled {
            opacity: 1 !important;
            background: rgba(255, 255, 255, 0.9) !important;
            border-color: rgba(120, 90, 130, 0.12) !important;
            box-shadow: 0 6px 16px rgba(120, 90, 130, 0.12) !important;
            transform: none !important;
            cursor: not-allowed !important;
        }
        .st-key-hall_prev button:disabled, .st-key-hall_next button:disabled,
        .st-key-hall_prev button:disabled p, .st-key-hall_next button:disabled p {
            color: #B7A6BE !important;
        }

        /* 位置指示点 */
        .hall-dots { display: flex; justify-content: center; align-items: center; gap: 10px; padding: 15px 0 6px 0; }
        .hall-dot { width: 9px; height: 9px; border-radius: 50%; background: rgba(120, 90, 130, 0.20); transition: all 0.2s; }
        .hall-dot.active { width: 26px; border-radius: 5px; background: #E46893; }

        /* ==== 输入区 ==== */
        [data-testid="stTextInput"] input {
            border: 1px solid var(--line) !important;
            border-radius: 14px !important;
            padding: 13px 18px !important;
            font-size: 15px !important;
            background: var(--surface-solid) !important;
            color: var(--text-main) !important;
            box-shadow: var(--shadow-soft) !important;
            transition: border-color 0.2s, box-shadow 0.2s !important;
        }
        [data-testid="stTextInput"] input::placeholder { color: var(--text-sub) !important; }
        [data-testid="stTextInput"] input:focus {
            border-color: var(--primary) !important;
            box-shadow: 0 0 0 3px rgba(232, 93, 138, 0.12) !important;
        }
        /* 隐藏输入未提交时框内的 "Press Enter to apply" 灰色小字提示（Streamlit 1.63 默认行为） */
        [data-testid="stTextInput"] [data-testid="InputInstructions"] { display: none !important; }
    </style>
    """, unsafe_allow_html=True)

    # 渲染侧边栏
    render_sidebar()

    # 根据当前状态路由到对应页面（群聊优先于单聊）
    gid = st.session_state.current_group_id
    cid = st.session_state.current_character_id

    if gid:
        render_group_page(gid)
    elif cid is None:
        render_home_page()
    elif cid == "settings":
        render_settings_page()
    elif cid == "charadmin":
        render_character_admin_page()
    else:
        render_chat_page(cid)

    # 底部版权（聊天页不显示，避免占底部妨碍输入区贴底）
    if cid is None or cid == "settings" or cid == "charadmin":
        st.markdown("""<div style='text-align:center;padding:20px;color:#A0AEC0;font-size:13px;'>💬 聊天大厅 v2.0 · Powered by Qwen2.5 + FastAPI + Streamlit</div>""", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
