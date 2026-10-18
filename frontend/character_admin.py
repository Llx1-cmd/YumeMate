"""角色管理页面（角色系统第二阶段）：独立 UI 模块，由 streamlit_app.main() 调用。

只做管理界面与接口对接（角色列表 / 启用状态 / 健康检查 / 手动刷新），
复用第一阶段后端接口：GET /api/characters、GET /api/characters/health、
POST /api/characters/{id}/enabled。不扩展角色编辑 / 删除 / 创建。
数据全部动态来自后端，不写死角色 ID；启停以服务端返回为准。
"""
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


def _render_entry(entry, chars_by_id):
    """单个角色卡片：头像 / 名称与 ID / 启用状态 / 健康摘要 / 详情 / 启停操作"""
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
                st.image(f"{BACKEND_URL}/api/characters/{cid}/avatar", width=56)
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
        elif enabled is not None:
            if st.button(
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
                st.rerun()


def render_character_admin_page():
    """角色管理页：角色列表 / 启用状态 / 健康检查详情 / 启停 / 手动刷新"""
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

    c1, c2 = st.columns([1, 5])
    with c1:
        if st.button("🔄 刷新", use_container_width=True):
            _invalidate()
            with st.spinner("正在刷新角色状态…"):
                cache = _fetch_all()
    with c2:
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
        _render_entry(entry, chars_by_id)