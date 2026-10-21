"""角色管理页面（角色系统第二/三/四阶段）：独立 UI 模块，由 streamlit_app.main() 调用。

第二阶段：角色列表 / 启用状态 / 健康检查 / 手动刷新。
第三阶段：每个角色「编辑配置」入口——编辑名称 / 简介（description，沿用
character.json 既有字段）/ 人设提示词（prompt.txt）/ 更换头像。
第四阶段：列表页「➕ 创建角色」入口（ID / 名称 / 简介 / 人设提示词 /
可选头像）；每个角色「🗑 删除」操作（checkbox 二次确认，显示名称与 ID）。
复用后端接口：GET /api/characters、GET /api/characters/health、
POST /api/characters/{id}/enabled，以及第三阶段新增的
GET|PUT /api/characters/{id}/profile、PUT /api/characters/{id}/prompt、
POST /api/characters/{id}/avatar，第四阶段新增的
POST /api/characters（创建）、DELETE /api/characters/{id}（删除）。
数据全部动态来自后端，不写死角色 ID；启停与保存均以服务端返回为准。
"""
import base64
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from config import settings

BACKEND_URL = f"http://{settings.BACKEND_HOST}:{settings.BACKEND_PORT}"

# 管理页数据缓存（session_state）：手动刷新 / 启停操作后清除重取，服务端为准
_CACHE_KEY = "_admin_cache"
# 启停操作结果（st.rerun 后仍能显示，避免成功/失败消息随 rerun 丢失）
_OP_MSG_KEY = "_admin_op_msg"
# 当前正在编辑配置的角色 ID（None = 角色列表视图）
_EDIT_KEY = "_admin_editing"
# 创建角色视图开关（None/False = 列表视图）
_CREATE_KEY = "_admin_creating"
# 待二次确认删除的角色 ID（None = 无待确认项）
_DEL_KEY = "_admin_del_confirm"


def _fetch_all():
    """拉取角色列表 + 健康报告。err 非空表示至少一个接口失败（旧数据须标注）。"""
    chars, health, err = [], None, None
    try:
        r = requests.get(f"{BACKEND_URL}/api/characters", timeout=5)
        if r.status_code == 200:
            chars = r.json().get("characters", [])
        else:
            err = f"角色列表接口异常（HTTP {r.status_code}）"
    except requests.exceptions.ConnectionError:
        err = "无法连接到后端服务（请确认后端已启动）"
    except Exception as e:
        err = f"角色列表请求异常：{type(e).__name__}"
    try:
        r = requests.get(f"{BACKEND_URL}/api/characters/health", timeout=10)
        if r.status_code == 200:
            health = r.json()
        elif err is None:
            err = f"健康检查接口异常（HTTP {r.status_code}）"
    except requests.exceptions.ConnectionError:
        if err is None:
            err = "无法连接到后端服务（请确认后端已启动）"
    except Exception as e:
        if err is None:
            err = f"健康检查请求异常：{type(e).__name__}"
    cache = {"chars": chars, "health": health, "err": err, "at": time.time()}
    st.session_state[_CACHE_KEY] = cache
    return cache


def _invalidate():
    """清除缓存：启停操作后 / 手动刷新时重取，保证以服务端状态为准"""
    st.session_state.pop(_CACHE_KEY, None)


def _set_enabled(cid, enabled):
    """调用后端启停接口，以服务端返回为准。返回 (ok, 消息文本)。"""
    try:
        r = requests.post(
            f"{BACKEND_URL}/api/characters/{cid}/enabled",
            json={"enabled": enabled},
            timeout=10,
        )
        if r.status_code == 200:
            d = r.json()
            if d.get("enabled") is enabled:
                note = (
                    "（状态文件有异常提示，见页面顶部）"
                    if not (d.get("state_file") or {}).get("ok")
                    else ""
                )
                return True, f"已{'启用' if enabled else '停用'}「{d.get('name') or cid}」{note}"
            return False, f"服务端返回状态不一致（enabled={d.get('enabled')}）"
        try:
            d = r.json()
            detail = d.get("detail") or d.get("error")
        except Exception:
            detail = None
        return False, f"操作失败（HTTP {r.status_code}）{'：' + detail if detail else ''}"
    except requests.exceptions.ConnectionError:
        return False, "无法连接到后端服务（请确认后端已启动）"
    except Exception as e:
        return False, f"请求异常：{type(e).__name__}"


def _api_json(method, path, timeout=30, **kw):
    """通用请求封装。返回 (status, data)：status=None 表示网络层失败。"""
    try:
        r = requests.request(method, f"{BACKEND_URL}{path}", timeout=timeout, **kw)
        try:
            d = r.json()
        except Exception:
            d = {}
        return r.status_code, d
    except requests.exceptions.ConnectionError:
        return None, {"detail": "无法连接到后端服务（请确认后端已启动）"}
    except Exception as e:
        return None, {"detail": f"请求异常：{type(e).__name__}"}


def _fetch_profile(cid):
    """拉取角色编辑数据（名称 / 简介 / 人设全文 / 头像扩展名）。

    附带 _at 时间戳：头像预览 URL 用它做 cache-busting，更换头像后重拉
    即可让浏览器请求新图（绕过缓存）。"""
    status, d = _api_json("GET", f"/api/characters/{cid}/profile")
    if status == 200 and "name" in d:
        d["_at"] = time.time()
        st.session_state[f"_edit_data_{cid}"] = d
        return d
    if status == 404:
        st.error(f"角色不存在或未加载：{cid}（配置损坏的角色无法编辑）")
    else:
        st.error(f"获取角色配置失败：{d.get('detail') or f'HTTP {status}'}")
    return None


def _leave_edit(cid):
    """退出编辑视图：清编辑状态 / 编辑数据 / 表单 widget（下次进入以服务端为准）"""
    for key in (
        _EDIT_KEY, f"_edit_data_{cid}", f"_ename_{cid}", f"_edesc_{cid}",
        f"_eprompt_{cid}", f"_eupcnt_{cid}",
        f"_ppupcnt_{cid}", f"_bgupcnt_{cid}",
        f"_ebgmode_{cid}", f"_ebgsrc_{cid}", f"_ebgcolor_{cid}",
    ):
        st.session_state.pop(key, None)
    # uploader key 带序号（上传成功后 +1 换新 widget 清空选择），按前缀清理
    for k in list(st.session_state.keys()):
        if k.startswith(f"_eavatar_{cid}_") or k.startswith(f"_eportrait_{cid}_") \
                or k.startswith(f"_ebg_{cid}_"):
            st.session_state.pop(k, None)
    _invalidate()
    st.rerun()


def _render_edit_page(cid):
    """角色配置编辑页：头像 / 名称与简介 / 人设提示词，分区块保存"""
    # 头像上传等操作结果（rerun 后显示，编辑页与列表页共用此消息通道）
    op = st.session_state.pop(_OP_MSG_KEY, None)
    if op:
        (st.success if op["ok"] else st.error)(op["text"])

    data = st.session_state.get(f"_edit_data_{cid}")
    if data is None:
        with st.spinner("正在读取角色配置…"):
            data = _fetch_profile(cid)
        if data is None:
            if st.button("← 返回角色列表"):
                _leave_edit(cid)
            return

    st.markdown(
        f"""
    <div style="text-align:center; padding:20px 20px 6px 20px;">
        <h1 style="color:#FF6B9D; font-size:26px;">✏️ 编辑配置：{data['name']}</h1>
    </div>
    """,
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns([1, 5])
    with c1:
        if st.button("← 返回角色列表", use_container_width=True):
            _leave_edit(cid)
    with c2:
        st.markdown(
            '<div style="color:#A0AEC0;font-size:13px;padding-top:8px;">'
            f'ID：{cid} · 保存以服务端结果为准</div>',
            unsafe_allow_html=True,
        )

    name_key = f"_ename_{cid}"
    desc_key = f"_edesc_{cid}"
    prompt_key = f"_eprompt_{cid}"
    # uploader key 带序号：file_uploader 的已选文件存于前端 widget state，
    # 对 session_state 赋值（被 Streamlit 禁止，抛
    # StreamlitValueAssignmentNotAllowedError）或 pop（只清后端副本）都清不掉
    # 前端显示；唯一可靠清空方式是上传成功后序号 +1 换 key，旧 widget 废弃、
    # 新 uploader 为全新空状态
    up_cnt_key = f"_eupcnt_{cid}"
    up_key = f"_eavatar_{cid}_{st.session_state.get(up_cnt_key, 0)}"
    # 表单初值只在此处设置一次；保存成功后服务端值与表单值一致，无需重置
    for k, v in ((name_key, data["name"]), (desc_key, data["description"]),
                 (prompt_key, data["prompt"])):
        if k not in st.session_state:
            st.session_state[k] = v

    # ---- 头像 ----
    with st.container(border=True):
        st.markdown("**🖼 头像**")
        h1, h2 = st.columns([1, 3])
        with h1:
            if data.get("avatar_ext"):
                # ?v= 时间戳破浏览器缓存：更换头像后重拉数据即显示新图
                st.image(
                    f"{BACKEND_URL}/api/characters/{cid}/avatar?v={int(data['_at'])}",
                    width=96,
                )
            else:
                st.markdown(
                    '<div style="width:96px;height:96px;border-radius:18px;'
                    "display:flex;align-items:center;justify-content:center;"
                    'background:rgba(120,90,130,0.10);font-size:40px;">👤</div>',
                    unsafe_allow_html=True,
                )
        with h2:
            up = st.file_uploader(
                "选择新头像（PNG / JPG / WEBP，≤5MB）",
                type=["png", "jpg", "jpeg", "webp"],
                key=up_key,
            )
            if st.button("📤 更换头像", key=f"_eup_{cid}", use_container_width=True):
                if up is None:
                    st.warning("请先选择图片文件")
                elif up.size > 5 * 1024 * 1024:
                    st.error("图片过大（超过 5MB），请压缩后再试")
                else:
                    b64 = base64.b64encode(up.getvalue()).decode("ascii")
                    with st.spinner("正在上传并校验图片…"):
                        status, d = _api_json(
                            "POST", f"/api/characters/{cid}/avatar",
                            json={"image": b64}, timeout=60,
                        )
                    if status == 200:
                        # 换 key 清空选择器（见 up_key 定义处注释）+ 清旧 key 遗留值
                        st.session_state.pop(up_key, None)
                        st.session_state[up_cnt_key] = (
                            st.session_state.get(up_cnt_key, 0) + 1
                        )
                        st.session_state[_OP_MSG_KEY] = {
                            "ok": True, "text": f"已更新「{d.get('name') or cid}」的头像",
                        }
                        _fetch_profile(cid)  # 重拉：avatar_ext + _at 更新
                        _invalidate()
                        # 侧边栏/大厅/聊天页的头像 URL 用 avatar_ver（头像 mtime）
                        # 破缓存——须清 streamlit_app 的角色列表缓存，rerun 后
                        # 重新 fetch 拿到新 ver，侧边栏头像才会换新 URL 立即刷新
                        st.session_state.characters_cache = None
                        st.rerun()  # 立即刷新预览
                    else:
                        st.error(f"更换头像失败：{d.get('detail') or f'HTTP {status}'}")

    # ---- 立绘（第四阶段补充）----
    with st.container(border=True):
        st.markdown("**🎭 立绘**")
        p1, p2 = st.columns([1, 3])
        with p1:
            if data.get("portrait_ext"):
                st.image(
                    f"{BACKEND_URL}/api/characters/{cid}/portrait?v={int(data['_at'])}",
                    width=96,
                )
            else:
                st.markdown(
                    '<div style="width:96px;height:96px;border-radius:18px;'
                    "display:flex;align-items:center;justify-content:center;"
                    'background:rgba(120,90,130,0.10);font-size:40px;">👤</div>',
                    unsafe_allow_html=True,
                )
        with p2:
            p_cnt_key = f"_ppupcnt_{cid}"
            port_key = f"_eportrait_{cid}_{st.session_state.get(p_cnt_key, 0)}"
            port = st.file_uploader(
                "选择新立绘（PNG / JPG / WEBP，≤5MB；聊天页大图与主页展示用）",
                type=["png", "jpg", "jpeg", "webp"],
                key=port_key,
            )
            if st.button("📤 更换立绘", key=f"_eport_{cid}", use_container_width=True):
                if port is None:
                    st.warning("请先选择图片文件")
                elif port.size > 5 * 1024 * 1024:
                    st.error("图片过大（超过 5MB），请压缩后再试")
                else:
                    b64 = base64.b64encode(port.getvalue()).decode("ascii")
                    with st.spinner("正在上传并校验立绘…"):
                        status, d = _api_json(
                            "POST", f"/api/characters/{cid}/portrait",
                            json={"image": b64}, timeout=60,
                        )
                    if status == 200:
                        st.session_state.pop(port_key, None)
                        st.session_state[p_cnt_key] = (
                            st.session_state.get(p_cnt_key, 0) + 1
                        )
                        st.session_state[_OP_MSG_KEY] = {
                            "ok": True, "text": f"已更新「{d.get('name') or cid}」的立绘",
                        }
                        _fetch_profile(cid)
                        _invalidate()
                        # 聊天页立绘 URL 无版本号走 no-cache 304，清列表缓存即可
                        st.session_state.characters_cache = None
                        st.rerun()
                    else:
                        st.error(f"更换立绘失败：{d.get('detail') or f'HTTP {status}'}")

    # ---- 背景（第四阶段补充，三选一）----
    with st.container(border=True):
        st.markdown("**🎨 背景（三选一：上传 / 复用已存在 / 纯色）**")
        if data.get("background_color"):
            cur = f"当前：无背景模式（纯色 {data['background_color']}）"
        elif data.get("background_ext"):
            cur = f"当前：背景图（{data['background_ext']}）"
        else:
            cur = "当前：未配置专属背景（回退全局默认背景）"
        st.markdown(
            f'<div style="color:#A0AEC0;font-size:12px;">{cur}</div>',
            unsafe_allow_html=True,
        )
        bg_mode_key = f"_ebgmode_{cid}"
        if bg_mode_key not in st.session_state:
            st.session_state[bg_mode_key] = (
                "无背景（使用纯色）" if data.get("background_color")
                else "上传背景图片"
            )
        bg_mode = st.radio(
            "背景来源", ["上传背景图片", "复用已存在背景", "无背景（使用纯色）"],
            key=bg_mode_key, horizontal=True,
        )
        bg_up = None
        copy_from = None
        bg_color = None
        bg_key = None
        if bg_mode == "上传背景图片":
            bg_cnt_key = f"_bgupcnt_{cid}"
            bg_key = f"_ebg_{cid}_{st.session_state.get(bg_cnt_key, 0)}"
            bg_up = st.file_uploader(
                "选择新背景（PNG / JPG / WEBP，≤5MB）",
                type=["png", "jpg", "jpeg", "webp"],
                key=bg_key,
            )
        elif bg_mode == "复用已存在背景":
            try:
                r = requests.get(f"{BACKEND_URL}/api/characters", timeout=5)
                chars = r.json().get("characters", []) if r.status_code == 200 else []
            except Exception:
                chars = []
            sources = [("default", "默认背景（现有全局背景）")]
            for ch in chars:
                if ch["id"] != cid:
                    sources.append((ch["id"], f"与「{ch['name']}」相同"))
            sel = st.selectbox(
                "背景来源（复制该背景文件为本角色专属，不影响原角色）",
                [s[1] for s in sources], key=f"_ebgsrc_{cid}",
            )
            copy_from = next(s[0] for s in sources if s[1] == sel)
        else:
            color_key = f"_ebgcolor_{cid}"
            if color_key not in st.session_state:
                st.session_state[color_key] = (
                    data.get("background_color") or "#F0E6F5"
                )
            bg_color = st.color_picker(
                "背景颜色（聊天页与主页主视图背景）", key=color_key
            )
        if st.button("💾 保存背景", key=f"_ebgsave_{cid}", type="primary",
                     use_container_width=True):
            body = {}
            if bg_mode == "上传背景图片":
                if bg_up is None:
                    st.warning("已选择「上传背景图片」，请选择背景文件")
                elif bg_up.size > 5 * 1024 * 1024:
                    st.error("图片过大（超过 5MB），请压缩后再试")
                else:
                    body["image"] = base64.b64encode(bg_up.getvalue()).decode("ascii")
            elif bg_mode == "复用已存在背景":
                body["copy_from"] = copy_from
            else:
                body["color"] = bg_color
            if body:
                with st.spinner("正在保存背景…"):
                    status, d = _api_json(
                        "POST", f"/api/characters/{cid}/background",
                        json=body, timeout=60,
                    )
                if status == 200:
                    st.session_state[_OP_MSG_KEY] = {
                        "ok": True,
                        "text": f"已更新「{d.get('name') or cid}」的背景",
                    }
                    if bg_mode == "上传背景图片" and bg_key:
                        st.session_state.pop(bg_key, None)
                        st.session_state[f"_bgupcnt_{cid}"] = (
                            st.session_state.get(f"_bgupcnt_{cid}", 0) + 1
                        )
                    _fetch_profile(cid)
                    _invalidate()
                    # 背景图/背景色在聊天页与主页生效需重新拉取角色列表
                    st.session_state.characters_cache = None
                    st.rerun()
                else:
                    st.error(f"保存背景失败：{d.get('detail') or f'HTTP {status}'}")

    # ---- 名称与简介 ----
    with st.container(border=True):
        st.markdown("**📝 名称与简介**")
        name = st.text_input("角色名称（必填，将显示在聊天与列表中）", key=name_key)
        st.text_area(
            "角色简介（character.json 的 description 字段）", key=desc_key, height=100
        )
        if st.button("💾 保存名称与简介", key=f"_esave_{cid}", type="primary",
                     use_container_width=True):
            if not name.strip():
                st.error("角色名称不能为空")
            else:
                with st.spinner("正在保存…"):
                    status, d = _api_json(
                        "PUT", f"/api/characters/{cid}/profile",
                        json={"name": name, "description": st.session_state[desc_key]},
                    )
                if status == 200:
                    new_name = (d.get("character") or {}).get("name") or name.strip()
                    st.success(f"已保存：{new_name}")
                    _fetch_profile(cid)
                    _invalidate()  # 列表里显示的名称同步刷新
                else:
                    st.error(f"保存失败：{d.get('detail') or f'HTTP {status}'}（原配置未改动）")

    # ---- 人设提示词 ----
    with st.container(border=True):
        st.markdown("**🎭 人设提示词（prompt.txt，保存后后续聊天即生效）**")
        st.text_area(
            "提示词全文（保留换行与中英日字符，禁止为空）",
            key=prompt_key, height=420,
        )
        if st.button("💾 保存人设提示词", key=f"_epsave_{cid}", type="primary",
                     use_container_width=True):
            if not st.session_state[prompt_key].strip():
                st.error("提示词不能为空")
            else:
                with st.spinner("正在保存并校验…"):
                    status, d = _api_json(
                        "PUT", f"/api/characters/{cid}/prompt",
                        json={"prompt": st.session_state[prompt_key]},
                    )
                if status == 200:
                    st.success(
                        f"已保存人设提示词（{d.get('prompt_length')} 字符，"
                        "已重新加载，后续聊天使用新人设）"
                    )
                    _fetch_profile(cid)
                else:
                    st.error(f"保存失败：{d.get('detail') or f'HTTP {status}'}（原提示词未改动）")


def _leave_create():
    """退出创建视图：清创建状态与表单 widget（下次进入为全新空表单）"""
    st.session_state.pop(_CREATE_KEY, None)
    for k in ("_cid_new", "_cname_new", "_csubtitle_new", "_cdesc_new",
              "_cprompt_new", "_cupcnt_new", "_cbg_mode_new", "_cbg_src_new",
              "_cbg_color_new"):
        st.session_state.pop(k, None)
    for k in list(st.session_state.keys()):
        if k.startswith("_cavatar_new_") or k.startswith("_cportrait_new_") \
                or k.startswith("_cbg_new_"):
            st.session_state.pop(k, None)
    _invalidate()


def _render_create_page():
    """创建角色页：ID / 名称 / 副标题 / 简介 / 人设提示词 / 头像 / 立绘 /
    背景三选一。

    校验以服务端为准（前端仅做即时提示）：ID 白名单正则、空名称、
    空提示词、重复 ID、已存在目录、背景三选一互斥均由 POST /api/characters
    拒绝。立绘/背景未提供时留空（不指向其他角色文件）；立绘/背景写
    frontend/assets/ 规范位置（第 66 条统一，与 yuuka/mika 一致）。"""
    op = st.session_state.pop(_OP_MSG_KEY, None)
    if op:
        (st.success if op["ok"] else st.error)(op["text"])

    st.markdown(
        """
    <div style="text-align:center; padding:20px 20px 6px 20px;">
        <h1 style="color:#FF6B9D; font-size:26px;">➕ 创建角色</h1>
    </div>
    """,
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns([1, 5])
    with c1:
        if st.button("← 返回角色列表", use_container_width=True):
            _leave_create()
    with c2:
        st.markdown(
            '<div style="color:#A0AEC0;font-size:13px;padding-top:8px;">'
            "校验以服务端为准 · 创建后自动进入角色列表</div>",
            unsafe_allow_html=True,
        )

    # 表单初值只在此处设置一次（widget key 赋值规则见 _render_edit_page 注释）
    for k, v in (("_cid_new", ""), ("_cname_new", ""), ("_csubtitle_new", ""),
                 ("_cdesc_new", ""), ("_cprompt_new", "")):
        if k not in st.session_state:
            st.session_state[k] = v

    cid = st.text_input(
        "角色 ID（必填，仅英文字母 / 数字 / 下划线 / 连字符，1~32 位）",
        key="_cid_new",
    )
    name = st.text_input("角色名称（必填，将显示在聊天与列表中）", key="_cname_new")
    st.text_input(
        "副标题（可选，显示在聊天大厅角色卡片上，如「三一综合学园茶话会会长」）",
        key="_csubtitle_new",
    )
    st.text_area("角色简介（可选）", key="_cdesc_new", height=100)
    st.text_area(
        "人设提示词（必填，写入 prompt.txt，保留换行与中英日字符）",
        key="_cprompt_new", height=300,
    )
    # 头像 / 立绘（均可选）：uploader key 带序号（提交失败后 +1 换新 widget 清空）
    up_key = f"_cavatar_new_{st.session_state.get('_cupcnt_new', 0)}"
    port_key = f"_cportrait_new_{st.session_state.get('_cupcnt_new', 0)}"
    up = st.file_uploader(
        "头像（可选，PNG / JPG / WEBP，≤5MB；不提供则使用默认头像）",
        type=["png", "jpg", "jpeg", "webp"],
        key=up_key,
    )
    port = st.file_uploader(
        "立绘（可选，PNG / JPG / WEBP，≤5MB；聊天页大图与主页展示用；"
        "不提供则聊天页留空占位，不会指向其他角色）",
        type=["png", "jpg", "jpeg", "webp"],
        key=port_key,
    )

    # ---- 背景三选一：上传 / 复用已存在 / 无背景（纯色）----
    st.markdown("**🎨 背景（三选一）**")
    bg_mode = st.radio(
        "背景来源",
        ["上传背景图片", "复用已存在背景", "无背景（使用纯色）"],
        key="_cbg_mode_new",
        horizontal=True,
    )
    bg_up = None
    copy_from = None
    bg_color = None
    if bg_mode == "上传背景图片":
        bg_key = f"_cbg_new_{st.session_state.get('_cupcnt_new', 0)}"
        bg_up = st.file_uploader(
            "背景图片（PNG / JPG / WEBP，≤5MB）",
            type=["png", "jpg", "jpeg", "webp"],
            key=bg_key,
        )
    elif bg_mode == "复用已存在背景":
        try:
            r = requests.get(f"{BACKEND_URL}/api/characters", timeout=5)
            chars = r.json().get("characters", []) if r.status_code == 200 else []
        except Exception:
            chars = []
        sources = [("default", "默认背景（现有全局背景）")]
        for ch in chars:
            sources.append((ch["id"], f"与「{ch['name']}」相同"))
        sel = st.selectbox(
            "背景来源（复制该背景文件为本角色专属，不影响原角色）",
            [s[1] for s in sources], key="_cbg_src_new",
        )
        copy_from = next(s[0] for s in sources if s[1] == sel)
    else:
        bg_color = st.color_picker(
            "背景颜色（聊天页与主页主视图背景）", "#F0E6F5", key="_cbg_color_new"
        )

    if st.button("✅ 创建角色", type="primary", use_container_width=True,
                 key="_create_submit"):
        # 前端即时提示（服务端会独立再校验）
        if not cid.strip() or not re.match(r"^[A-Za-z0-9_-]{1,32}$", cid.strip()):
            st.error("角色 ID 只能包含英文字母、数字、下划线和连字符（1~32 位）")
        elif not name.strip():
            st.error("角色名称不能为空")
        elif not st.session_state["_cprompt_new"].strip():
            st.error("提示词不能为空")
        elif any(u is not None and u.size > 5 * 1024 * 1024
                 for u in (up, port, bg_up)):
            st.error("图片过大（超过 5MB），请压缩后再试")
        elif bg_mode == "上传背景图片" and bg_up is None:
            st.error("已选择「上传背景图片」，请选择背景文件")
        else:
            body = {
                "id": cid.strip(),
                "name": name.strip(),
                "subtitle": st.session_state["_csubtitle_new"].strip(),
                "description": st.session_state["_cdesc_new"],
                "prompt": st.session_state["_cprompt_new"],
                "image": base64.b64encode(up.getvalue()).decode("ascii") if up else None,
                "portrait": base64.b64encode(port.getvalue()).decode("ascii") if port else None,
            }
            if bg_mode == "上传背景图片":
                body["background"] = base64.b64encode(bg_up.getvalue()).decode("ascii")
            elif bg_mode == "复用已存在背景":
                body["background_copy_from"] = copy_from
            else:
                body["background_color"] = bg_color
            with st.spinner("正在创建角色…"):
                status, d = _api_json(
                    "POST", "/api/characters", json=body, timeout=60,
                )
            if status == 200:
                new_name = (d.get("character") or {}).get("name") or name.strip()
                st.session_state[_OP_MSG_KEY] = {
                    "ok": True, "text": f"已创建角色「{new_name}」",
                }
                _leave_create()
                _invalidate()
                # 侧边栏/大厅/聊天页的角色列表来自 streamlit_app 缓存，一并清掉
                st.session_state.characters_cache = None
                st.rerun()
            else:
                # 失败：换 uploader key 清空选择（用户重新提交时表单保留已填文本）
                st.session_state.pop(up_key, None)
                st.session_state.pop(port_key, None)
                st.session_state["_cupcnt_new"] = (
                    st.session_state.get("_cupcnt_new", 0) + 1
                )
                st.error(
                    f"创建失败：{d.get('detail') or f'HTTP {status}'}"
                    "（本次文件已清理，可修改后重试）"
                )


def _delete_character_api(cid):
    """调用后端删除接口。返回 (ok, 消息文本)。"""
    status, d = _api_json("DELETE", f"/api/characters/{cid}", timeout=60)
    if status == 200:
        note = f"；{d.get('cleanup_warning')}" if d.get("cleanup_warning") else ""
        return True, f"已删除角色「{d.get('name') or cid}」{note}"
    detail = d.get("detail") or d.get("error")
    if status is None:
        return False, detail or "请求异常"
    return False, f"删除失败（HTTP {status}）{'：' + detail if detail else ''}"


def _health_summary(entry):
    """健康摘要。区分 loaded 与 config_ok：loaded=True 不等同配置健康。

    返回 (kind, 文本)：ok=健康 / warn=配置通过但有提示级异常 / bad=异常 / unknown=未知。
    tts_ok=None（未配置 TTS）不算异常。
    """
    if entry is None:
        return "unknown", "健康状态未知（健康检查接口失败）"
    if not entry.get("loaded"):
        return "bad", "未加载 · 配置损坏（当前不可用于聊天）"
    if not entry.get("config_ok"):
        return "bad", "已加载但配置异常（详见检查结果）"
    notes = []
    if not entry.get("prompt_ok"):
        notes.append("提示词异常")
    if not entry.get("avatar_ok"):
        notes.append("头像缺失")
    if entry.get("tts_ok") is False:
        notes.append("TTS 异常（不影响文字聊天）")
    if notes:
        return "warn", "配置通过 · " + "、".join(notes)
    return "ok", "健康"


_SUMMARY_STYLE = {
    "ok": ("#52C41A", "✅"),
    "warn": ("#E6A23C", "⚠️"),
    "bad": ("#F56C6C", "❌"),
    "unknown": ("#A0AEC0", "？"),
}


def _check_line(label, val, none_text):
    """单个检查项行：True=绿 / False=红 / None=灰（未配置或状态未知，语义由 none_text 区分）"""
    if val is True:
        color, icon, tail = "#52C41A", "✅", ""
    elif val is False:
        color, icon, tail = "#F56C6C", "❌", ""
    else:
        color, icon, tail = "#A0AEC0", "○", f"（{none_text}）"
    return (
        f'<div style="font-size:13px;color:{color};padding:2px 0;">'
        f"{icon} {label}{tail}</div>"
    )


def _render_entry(entry, chars_by_id, ver):
    """单个角色卡片：头像 / 名称与 ID / 启用状态 / 健康摘要 / 详情 / 启停与编辑"""
    cid = entry.get("id") or entry.get("dir")
    char = chars_by_id.get(cid)
    name = (char or {}).get("name") or cid
    subtitle = (char or {}).get("subtitle") or ""
    avatar_ext = (char or {}).get("avatar_ext")
    enabled = entry.get("enabled")
    loaded = entry.get("loaded")

    with st.container(border=True):
        top = st.columns([0.12, 0.64, 0.24])
        with top[0]:
            if avatar_ext:
                # ?v= 破浏览器缓存：换头像 / 手动刷新后 URL 变化，强制重新加载
                st.image(
                    f"{BACKEND_URL}/api/characters/{cid}/avatar?v={ver}", width=56
                )
            else:
                st.markdown(
                    '<div style="width:56px;height:56px;border-radius:14px;'
                    "display:flex;align-items:center;justify-content:center;"
                    'background:rgba(120,90,130,0.10);font-size:26px;">👤</div>',
                    unsafe_allow_html=True,
                )
        with top[1]:
            sub_html = (
                f'<br><span style="color:#8A8490;font-size:12px;">{subtitle}</span>'
                if subtitle
                else ""
            )
            st.markdown(
                f'<div style="font-size:16px;font-weight:700;color:#4A4A6A;">{name}'
                f'　<span style="color:#A0AEC0;font-size:12px;font-weight:400;">{cid}</span></div>'
                f"{sub_html}",
                unsafe_allow_html=True,
            )
        with top[2]:
            if enabled is True:
                badge = '<span style="color:#52C41A;font-weight:700;">✅ 已启用</span>'
            elif enabled is False:
                badge = '<span style="color:#F56C6C;font-weight:700;">⛔ 已停用</span>'
            else:
                badge = '<span style="color:#A0AEC0;">？状态未知</span>'
            st.markdown(
                f'<div style="padding-top:16px;text-align:right;">{badge}</div>',
                unsafe_allow_html=True,
            )

        kind, text = _health_summary(entry)
        color, icon = _SUMMARY_STYLE[kind]
        st.markdown(
            f'<div style="font-size:13px;color:{color};padding:4px 0 2px 0;">'
            f"{icon} 健康状态：{text}</div>",
            unsafe_allow_html=True,
        )

        with st.expander("🔍 查看详细检查结果"):
            st.markdown(
                _check_line("已加载进后端（可被聊天使用）", entry.get("loaded"), "状态未知")
                + _check_line(
                    "配置检查通过（JSON 解析 + 必需字段）", entry.get("config_ok"), "状态未知"
                )
                + _check_line("提示词文件", entry.get("prompt_ok"), "状态未知")
                + _check_line("头像文件", entry.get("avatar_ok"), "状态未知")
                + _check_line("TTS 配置与相关文件", entry.get("tts_ok"), "未配置 TTS"),
                unsafe_allow_html=True,
            )
            issues = entry.get("issues") or []
            if issues:
                st.markdown("**异常详情：**")
                for i in issues:
                    st.markdown(
                        f'<div style="font-size:13px;color:#F56C6C;padding:1px 0;">- {i}</div>',
                        unsafe_allow_html=True,
                    )
            elif entry.get("loaded"):
                st.markdown(
                    '<div style="font-size:13px;color:#A0AEC0;">未发现异常。</div>',
                    unsafe_allow_html=True,
                )

        if not loaded:
            st.info("该角色目录存在但配置损坏，未加载进后端——修复配置后点「🔄 刷新」即可管理。")
        else:
            ops = st.columns(3)
            with ops[0]:
                edit_clicked = st.button(
                    "✏️ 编辑配置", key=f"adm_edit_{cid}", use_container_width=True
                )
            with ops[1]:
                if enabled is not None and st.button(
                    "⏸ 停用该角色" if enabled else "▶ 启用该角色",
                    key=f"adm_toggle_{cid}",
                    use_container_width=True,
                    type="primary" if not enabled else "secondary",
                ):
                    # 目标状态是当前状态的取反（enabled=True 时点击=停用→传 False）
                    target = not enabled
                    # 防重复点击：同步请求 + spinner（执行期间 UI 锁定，rerun 后按钮复位）
                    with st.spinner("正在更新状态…"):
                        ok_set, msg = _set_enabled(cid, target)
                    st.session_state[_OP_MSG_KEY] = {"ok": ok_set, "text": msg}
                    # 无论成败都重取：失败时也重新读取服务端状态，避免 UI 与实际不一致
                    _invalidate()
                    # 侧边栏/大厅/聊天页的「在线/离线」显示用 characters 里的
                    # enabled 字段——须清 streamlit_app 的角色列表缓存，rerun 后
                    # 重新 fetch 拿到新状态，各页面状态文案才会即时更新
                    st.session_state.characters_cache = None
                    st.rerun()
            with ops[2]:
                if st.button("🗑 删除", key=f"adm_del_{cid}", use_container_width=True):
                    # 进入该角色的二次确认视图（rerun 后在本卡片内展开确认区）
                    st.session_state[_DEL_KEY] = cid
                    st.rerun()
            if edit_clicked:
                st.session_state[_EDIT_KEY] = cid
                st.rerun()

        # ---- 删除二次确认（checkbox + 名称/ID 展示，服务端 DELETE 为准）----
        if st.session_state.get(_DEL_KEY) == cid:
            st.warning(
                f"⚠️ 将永久删除角色「{name}」（ID：{cid}）及其目录内的全部文件"
                "（配置 / 提示词 / 头像）。其他角色不受影响。"
            )
            confirmed = st.checkbox("我确认删除该角色", key=f"adm_delck_{cid}")
            d1, d2 = st.columns(2)
            with d1:
                if st.button(
                    "🗑 确认删除", key=f"adm_delok_{cid}", use_container_width=True,
                    type="primary", disabled=not confirmed,
                ):
                    with st.spinner("正在删除…"):
                        ok_del, msg = _delete_character_api(cid)
                    st.session_state[_OP_MSG_KEY] = {"ok": ok_del, "text": msg}
                    if ok_del:
                        st.session_state.pop(_DEL_KEY, None)
                        # 清该角色的单聊会话历史（浏览器会话数据，删除后
                        # 重建同名 ID 不会冒出旧历史；其他角色历史不动）
                        st.session_state.get("conversations", {}).pop(cid, None)
                        # 当前正在该角色聊天页时重置路由回主页（管理页激活时
                        # current_character_id="charadmin"，不受影响）
                        if st.session_state.get("current_character_id") == cid:
                            st.session_state.current_character_id = None
                    # 失败时保留确认状态，可修改后重试或取消
                    _invalidate()
                    st.session_state.characters_cache = None
                    st.rerun()
            with d2:
                if st.button("取消", key=f"adm_delno_{cid}", use_container_width=True):
                    st.session_state.pop(_DEL_KEY, None)
                    st.rerun()


def render_character_admin_page():
    """角色管理页：列表 / 启停 / 健康检查 / 手动刷新（第二阶段）；
    点「编辑配置」进入单角色编辑视图（第三阶段）；
    点「➕ 创建角色」进入创建视图（第四阶段）"""
    editing = st.session_state.get(_EDIT_KEY)
    if editing:
        _render_edit_page(editing)
        return
    if st.session_state.get(_CREATE_KEY):
        _render_create_page()
        return

    st.markdown(
        """
    <div style="text-align:center; padding:40px 20px 10px 20px;">
        <h1 style="color:#FF6B9D; font-size:32px;">👤 角色管理</h1>
    </div>
    """,
        unsafe_allow_html=True,
    )

    # 启停操作结果（rerun 后在此显示，成功/失败都以服务端返回为准）
    op = st.session_state.pop(_OP_MSG_KEY, None)
    if op:
        (st.success if op["ok"] else st.error)(op["text"])

    cache = st.session_state.get(_CACHE_KEY)
    if cache is None:
        with st.spinner("正在获取角色状态…"):
            cache = _fetch_all()

    c1, c2, c3 = st.columns([1, 1, 4])
    with c1:
        if st.button("🔄 刷新", use_container_width=True):
            _invalidate()
            with st.spinner("正在刷新角色状态…"):
                cache = _fetch_all()
    with c2:
        if st.button("➕ 创建角色", use_container_width=True):
            st.session_state[_CREATE_KEY] = True
            st.rerun()
    with c3:
        st.markdown(
            '<div style="color:#A0AEC0;font-size:13px;padding-top:8px;">'
            f'数据更新于 {datetime.fromtimestamp(cache["at"]).strftime("%H:%M:%S")}</div>',
            unsafe_allow_html=True,
        )

    # 接口失败：明确提示旧数据，不假装成功
    if cache.get("err"):
        st.error(
            f"⚠️ {cache['err']}——当前显示的可能不是最新数据，请点「🔄 刷新」重试。"
        )

    # 状态文件损坏：可理解的错误 + 安全处理说明（路径由后端过滤，不暴露绝对路径）
    sf = ((cache.get("health") or {}).get("state_file")) or {}
    if sf and not sf.get("ok"):
        extra = f"；备份文件：{sf.get('corrupt_backup')}" if sf.get("corrupt_backup") else ""
        st.error(
            f"⚠️ 角色启用状态文件损坏：{sf.get('error', '未知原因')}{extra}。"
            "已安全回退为「全部默认启用」，用户数据未丢失；"
            "修复文件后点「🔄 刷新」，或重新启用角色即可重建状态文件。"
        )

    chars = cache.get("chars") or []
    health_chars = ((cache.get("health") or {}).get("characters")) or []
    if not chars and not health_chars and not cache.get("err"):
        st.info("暂无角色——请将角色目录放入 characters/ 目录后点「🔄 刷新」。")
        return

    chars_by_id = {c["id"]: c for c in chars}
    if health_chars:
        # 全量发现的角色（含配置损坏未加载的，健康报告为准）
        entries = health_chars
    else:
        # 健康接口失败时退化为角色列表（健康检查项显示「状态未知」）
        entries = [
            {"id": c["id"], "dir": c["id"], "loaded": True,
             "enabled": c.get("enabled"), "issues": []}
            for c in chars
        ]

    for entry in entries:
        _render_entry(entry, chars_by_id, int(cache["at"]))