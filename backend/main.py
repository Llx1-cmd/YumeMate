from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import List, Dict
import uvicorn
import asyncio
import json
from config import settings
from services.llm_service import llm_service
from services.character_service import character_service
from services.character_state import character_state
from services.tts_service import tts_service
from services.group_service import group_service

app = FastAPI(
    title="YuukaChat API",
    description="优香AI聊天系统后端",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """启动即后台预加载当前生效模型（上次选择已从 model_state.json 恢复）。

    不阻塞启动流程；模型已在 Ollama 内存中时跳过，不重复加载。
    """
    target = llm_service.effective_model_now()
    print(f"[Startup] 当前生效模型: {target or '（未配置）'}，触发后台预加载")
    llm_service.start_preload()


class ChatMessage(BaseModel):
    message: str
    history: List[Dict] = []
    character_id: str = "yuuka"


class GroupChatMessage(BaseModel):
    message: str
    # 共享群聊历史：role 为 "user" / 角色id（如 "yuuka"/"mika"），保持顺序
    history: List[Dict] = []
    # 成员列表（按回复顺序），本阶段前端只传 ["yuuka", "mika"]，未来可扩展
    members: List[str] = []


class GroupCreate(BaseModel):
    """创建群聊（第五阶段）：名称只做显示（群 ID 服务端生成，不进路径），
    members 为初始成员（至少一个有效角色）"""
    name: str
    members: List[str]


class GroupMemberAdd(BaseModel):
    """邀请角色加入群聊（第五阶段）"""
    member_id: str


class GroupRename(BaseModel):
    """修改群名称（第六阶段）：仅动态群；名称只做显示，不进路径/ID"""
    name: str


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)


manager = ConnectionManager()

# 正在被活动聊天流程使用的角色计数（第四阶段删除安全检查）：
# chat/group/tts 请求开始时对涉及角色 +1、结束时 -1（asyncio 单线程事件
# loop 内同步增减，无竞态）；删除时计数 > 0 则 409 拒绝。
# 限制：/ws/chat 流式端点不计数（前端实际使用 /api/chat，未用 WebSocket）。
chat_inflight: Dict[str, int] = {}


def _inflight_add(ids) -> None:
    for i in ids:
        chat_inflight[i] = chat_inflight.get(i, 0) + 1


def _inflight_release(ids) -> None:
    for i in ids:
        chat_inflight[i] = max(0, chat_inflight.get(i, 1) - 1)


@app.get("/")
async def root():
    return {"message": "ChatHall API is running!", "status": "ok"}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "characters_loaded": len(character_service._characters),
    }


# ==================== 角色相关接口 ====================

@app.get("/api/characters")
async def list_characters():
    """返回所有可用角色列表（公开信息，不含人设 prompt）+ 启用状态（新增可选
    字段 enabled，旧前端不受影响）"""
    chars = [
        {**c, "enabled": character_state.is_enabled(c["id"])}
        for c in character_service.list_public()
    ]
    return {"characters": chars}


class CharacterEnabledSwitch(BaseModel):
    enabled: bool


class CharacterProfileUpdate(BaseModel):
    """编辑角色名称与简介（character.json 已有字段，沿用原格式）"""
    name: str
    description: str = ""


class CharacterPromptUpdate(BaseModel):
    prompt: str


class CharacterAvatarUpload(BaseModel):
    """头像上传：图片字节 base64 编码（避免 multipart 额外依赖）"""
    image: str


class CharacterBackgroundUpdate(BaseModel):
    """更换背景（第四阶段补充）：三选一互斥——image（上传 base64）/
    copy_from（复用已存在："default" 或角色 id）/ color（无背景纯色 hex）"""
    image: str = None
    copy_from: str = None
    color: str = None


class CharacterCreate(BaseModel):
    """创建新角色（第四阶段）：头像/立绘/背景可选（base64）。

    subtitle 可选（第 66 条统一：character.json 字段结构与 yuuka/mika 一致）。
    立绘/背景写 frontend/assets/ 规范位置（与现有角色相同）。
    背景三选一（互斥）：background（上传）/ background_copy_from（复用
    已存在背景："default" 或角色 id）/ background_color（无背景，主视图
    纯色）；全不提供则不写背景（前端回退全局默认背景）。"""
    id: str
    name: str
    subtitle: str = ""
    description: str = ""
    prompt: str
    image: str = None
    portrait: str = None
    background: str = None
    background_copy_from: str = None
    background_color: str = None


@app.get("/api/characters/health")
async def characters_health():
    """全部角色健康检查汇总：「已发现 / 配置检查通过 / 已启用」分开表示，
    含逐项诊断（JSON 解析、必需字段、提示词、头像、模型与 TTS 配置完整性）。
    纯文件系统 + JSON 检查，不调 Ollama 生成、不实际合成语音；
    TTS 配置异常只记录 tts_ok=False，不阻止纯文字聊天。"""
    report = character_state.health_report()
    # 安全过滤：不向前端暴露绝对本地路径（path 移除、备份只保留文件名）
    sf = report.get("state_file")
    if isinstance(sf, dict):
        sf.pop("path", None)
        backup = sf.get("corrupt_backup")
        if backup:
            sf["corrupt_backup"] = backup.replace("\\", "/").rsplit("/", 1)[-1]
    return report


@app.post("/api/characters/{character_id}/enabled")
async def set_character_enabled(character_id: str, m: CharacterEnabledSwitch):
    """设置角色启用/停用状态（独立状态文件 backend/data/character_state.json，
    不修改角色配置文件；新角色无记录默认启用）"""
    cfg = character_service.get(character_id)  # 不存在抛 404
    state_diag = character_state.set_enabled(character_id, m.enabled)
    return {
        "status": "success",
        "character_id": character_id,
        "name": cfg.name,
        "enabled": m.enabled,
        "state_file": state_diag,
    }


@app.get("/api/characters/{character_id}")
async def get_character(character_id: str):
    """返回单个角色的公开信息"""
    cfg = character_service.get(character_id)
    return cfg.to_public_dict()


# ==================== 角色创建 / 删除（第四阶段） ====================

@app.post("/api/characters")
async def create_character_endpoint(m: CharacterCreate):
    """创建新角色：服务端独立校验（ID 白名单正则 / 空名称 / 空提示词 /
    重复 ID / 已存在目录 / 目录路径限制在 characters/ 直接子目录），
    写 character.json + prompt.txt 并加载进内存；头像可选（base64，
    共用更换头像的安全校验规则），未提供则留空（不指向其他角色文件）。
    背景三选一（上传 / 复用已存在 / 无背景颜色，互斥），全不提供则回退
    全局默认背景。任何图片校验/写入失败回滚本次创建（目录为本次新建），
    不误删原有目录。"""
    import base64

    def _b64(v):
        if not v:
            return None
        try:
            return base64.b64decode(v, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="图片数据不是有效的 base64 编码")

    cfg = character_service.create_character(
        m.id, m.name, m.prompt, m.description,
        subtitle=m.subtitle,
        avatar_data=_b64(m.image),
        portrait_data=_b64(m.portrait),
        background_data=_b64(m.background),
        background_copy_from=m.background_copy_from,
        background_color=m.background_color,
    )
    return {"status": "success", "character": cfg.to_public_dict()}


@app.delete("/api/characters/{character_id}")
async def delete_character_endpoint(character_id: str):
    """删除角色：先检查是否正被活动聊天流程使用（in-flight 计数，使用中 409
    拒绝）；再 rename 到 characters/.deleting-* 隐藏目录（原子操作，后续任何
    步骤失败原目录都不在原地、不参与重扫），清内存缓存，清启用状态记录，
    最后 rmtree 暂存目录（失败返回 cleanup_warning，角色已一致地消失）。
    禁止路径穿越；只删该角色自己的目录/状态/缓存，其他角色不受影响。"""
    if chat_inflight.get(character_id, 0) > 0:
        raise HTTPException(
            status_code=409,
            detail="该角色正在被聊天流程使用，请稍后再删除",
        )
    result = character_service.delete_character(character_id)
    character_state.remove_record(character_id)
    chat_inflight.pop(character_id, None)
    return {"status": "success", **result}


# ==================== 角色配置编辑（第三阶段） ====================

@app.get("/api/characters/{character_id}/profile")
async def get_character_profile(character_id: str):
    """编辑页数据：名称 / 简介 / 人设提示词全文（管理编辑用途）+ 当前头像扩展名"""
    cfg = character_service.get(character_id)  # 不存在抛 404
    return {
        "id": cfg.id,
        "name": cfg.name,
        "description": cfg.description,
        "prompt": cfg.prompt,
        "avatar_ext": cfg._get_avatar_ext(),
        "portrait_ext": cfg._get_portrait_ext(),
        "background_color": cfg.background_color,
        "background_ext": cfg._get_background_ext(),
    }


@app.put("/api/characters/{character_id}/profile")
async def update_character_profile(character_id: str, m: CharacterProfileUpdate):
    """编辑角色名称与简介：服务端校验（名称去空白、禁止为空），原子写回
    character.json 并重载内存，返回最新公开信息（以服务端结果为准）"""
    pub = character_service.update_profile(character_id, m.name, m.description)
    return {"status": "success", "character": pub}


@app.put("/api/characters/{character_id}/prompt")
async def update_character_prompt(character_id: str, m: CharacterPromptUpdate):
    """编辑人设提示词：禁止空提示词，原文写回 prompt.txt（保留换行与
    中英日字符），保存后重读校验一致并重载内存（后续聊天即用新人设）"""
    result = character_service.update_prompt(character_id, m.prompt)
    return {"status": "success", **result}


@app.post("/api/characters/{character_id}/avatar")
async def update_character_avatar(character_id: str, m: CharacterAvatarUpload):
    """更换角色头像：base64 解码后由服务端校验（大小 / PIL 可解码 /
    PNG-JPG-WEBP 白名单），写入角色目录内安全路径，失败回滚"""
    import base64
    try:
        data = base64.b64decode(m.image, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="图片数据不是有效的 base64 编码")
    result = character_service.update_avatar(character_id, data)
    return {"status": "success", **result}


@app.post("/api/characters/{character_id}/portrait")
async def update_character_portrait(character_id: str, m: CharacterAvatarUpload):
    """更换角色立绘（第四阶段补充）：base64 解码后由服务端校验（同头像
    规则），写 characters/{id}/portrait.{ext}（与头像同目录），失败回滚"""
    import base64
    try:
        data = base64.b64decode(m.image, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="图片数据不是有效的 base64 编码")
    result = character_service.update_portrait(character_id, data)
    return {"status": "success", **result}


@app.post("/api/characters/{character_id}/background")
async def update_character_background(character_id: str, m: CharacterBackgroundUpdate):
    """更换角色背景（第四阶段补充，三选一互斥）：上传（image）/ 复用已存在
    （copy_from="default" 或角色 id，复制文件不改其他角色）/ 无背景纯色
    （color hex，写 character.json 的 background_color 字段）"""
    import base64
    data = None
    if m.image:
        try:
            data = base64.b64decode(m.image, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="图片数据不是有效的 base64 编码")
    result = character_service.update_background(
        character_id, image_data=data, copy_from=m.copy_from, color=m.color
    )
    return {"status": "success", **result}


@app.get("/api/characters/{character_id}/avatar")
async def get_character_avatar(character_id: str, request: Request):
    """返回角色头像文件（前端 <img src=...> 直接用）。
    Cache-Control: no-cache——浏览器可缓存但每次展示前须向服务器重新验证
    （比对 etag 命中回 304 空体，几乎零开销），避免 heuristic 缓存导致
    更换头像后旧图不刷新。
    第 62 条补：FileResponse 只发 ETag 不处理 If-None-Match，no-cache 下
    浏览器每次 rerun 都整图重拉；此处显式判 304。"""
    cfg = character_service.get(character_id)
    avatar_path = cfg.get_avatar_path()
    if not avatar_path or not avatar_path.exists():
        return JSONResponse(
            status_code=404,
            content={"error": "角色未配置头像"}
        )
    stat = avatar_path.stat()
    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    if etag in request.headers.get("if-none-match", ""):
        return Response(status_code=304, headers={
            "ETag": etag, "Cache-Control": "no-cache"})
    return FileResponse(
        str(avatar_path),
        headers={"Cache-Control": "no-cache", "ETag": etag},
    )


def _serve_character_image(path, request: Request, missing_detail: str):
    """角色目录图片文件统一响应（portrait/background 共用）：
    no-cache 协商缓存（etag 比对命中回 304，同 avatar 端点模式）。"""
    if not path or not path.exists():
        return JSONResponse(status_code=404, content={"error": missing_detail})
    stat = path.stat()
    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    if etag in request.headers.get("if-none-match", ""):
        return Response(status_code=304, headers={
            "ETag": etag, "Cache-Control": "no-cache"})
    return FileResponse(str(path), headers={
        "Cache-Control": "no-cache", "ETag": etag})


@app.get("/api/characters/{character_id}/portrait")
async def get_character_portrait_file(character_id: str, request: Request):
    """返回角色立绘文件：优先规范位置 frontend/assets/character/{id}.{ext}
    （第 66 条统一，与 yuuka/mika 一致），回退角色目录 portrait.{ext}
    （第四阶段旧位置，兼容读取）；前端聊天页大图/主页 Hero/编辑页预览用"""
    cfg = character_service.get(character_id)
    path = None
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = _ASSETS_DIR / "character" / f"{character_id}{ext}"
        if p.exists():
            path = p
            break
    if path is None:
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            p = cfg.dir_path / f"portrait{ext}"
            if p.exists():
                path = p
                break
    return _serve_character_image(path, request, "角色未配置立绘")


@app.get("/api/characters/{character_id}/background")
async def get_character_background_file(character_id: str, request: Request):
    """返回角色背景文件：优先规范位置 frontend/assets/background/{id}.{ext}
    （第 66 条统一），回退角色目录 background.{ext}（旧位置，兼容读取）"""
    cfg = character_service.get(character_id)
    path = None
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = _ASSETS_DIR / "background" / f"{character_id}{ext}"
        if p.exists():
            path = p
            break
    if path is None:
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            p = cfg.dir_path / f"background{ext}"
            if p.exists():
                path = p
                break
    return _serve_character_image(path, request, "角色未配置背景")


# ==================== 前端静态资产（立绘/背景，第 61 条） ====================
# 此前立绘/背景由 Streamlit 以 base64 内嵌进 st.markdown 的 HTML（mika 立绘
# 1.6MB → base64 约 2.2MB），每次 fragment rerun 都参与 React diff/innerHTML
# 替换，是切角色时整页空白帧的主因。改为 URL 引用后 HTML 缩到几十字节，
# 图片走浏览器 HTTP 缓存（FileResponse ETag/304），切换角色秒出。
from pathlib import Path as _Path
import re as _re

_ASSETS_DIR = (_Path(__file__).resolve().parent.parent / "frontend" / "assets").resolve()
_ASSET_SUBDIRS = {"character": "character", "background": "background"}
_ASSET_NAME_RE = _re.compile(r"^[A-Za-z0-9_.\-]+$")


@app.get("/api/assets/{subdir}/{filename}")
async def get_frontend_asset(subdir: str, filename: str, request: Request):
    """前端 assets 静态文件（立绘/背景）。文件名白名单 + resolve 防路径穿越；
    no-cache 协商缓存：立绘更新后 etag 变化即得新图。
    第 62 条补：FileResponse 不处理 If-None-Match（无 304 判定），no-cache 下
    浏览器每次 rerun 都整图重拉（实测每次 rerun mika.png 1.6MB 等全量 200）。
    显式比对 etag 命中即回 304 空体，rerun 零重传。"""
    sub = _ASSET_SUBDIRS.get(subdir)
    if sub is None or not _ASSET_NAME_RE.match(filename):
        raise HTTPException(status_code=404, detail="资产不存在")
    p = (_ASSETS_DIR / sub / filename).resolve()
    if _ASSETS_DIR not in p.parents or not p.is_file():
        raise HTTPException(status_code=404, detail="资产不存在")
    stat = p.stat()
    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    if etag in request.headers.get("if-none-match", ""):
        return Response(status_code=304, headers={
            "ETag": etag, "Cache-Control": "no-cache"})
    return FileResponse(str(p), headers={
        "Cache-Control": "no-cache", "ETag": etag})


# ==================== 语音接口（GPT-SoVITS，只增不改，不影响聊天 API） ====================

@app.get("/api/tts/status")
async def tts_status():
    """GPT-SoVITS 服务是否在线（前端据此决定是否渲染语音播放器）"""
    return {"tts_available": tts_service.available()}


@app.get("/api/tts-audio")
async def tts_audio(character_id: str, text: str):
    """把中文回复合成为角色日语语音（WAV）：内部完成 中→日 翻译 + GPT-SoVITS 合成。

    前端用 <audio src=...> 由浏览器后台拉取，不阻塞聊天文字显示；
    相同 (角色, 文本) 命中服务端缓存，不重复生成。
    """
    cfg = character_service.get(character_id)  # 角色不存在时抛 404
    # 停用角色不可用（连文字聊天都不能用，TTS 附属能力同样拦截）
    if not character_state.is_enabled(character_id):
        return JSONResponse(
            status_code=403,
            content={"error": "角色已停用，无法合成语音"},
        )
    tts_cfg = cfg.tts
    if not tts_cfg.get("refer_wav_path"):
        return JSONResponse(
            status_code=503,
            content={"error": "该角色未配置语音"},
        )
    _inflight_add([character_id])
    try:
        wav = await asyncio.to_thread(
            tts_service.synthesize,
            character_id,
            tts_cfg,
            llm_service._effective_model(cfg.to_full_dict()),  # 翻译跟随当前生效模型（与聊天一致，避免双模型驻留）
            text,
        )
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"error": f"语音生成失败: {e}"},
        )
    finally:
        _inflight_release([character_id])
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ==================== 聊天接口 ====================

@app.post("/api/chat")
async def chat_endpoint(chat: ChatMessage):
    """同步聊天：发送消息 + 历史 + character_id，返回完整回复"""
    # 新请求使用角色前验证：不存在 404、已停用 403（后端拦截，不只前端隐藏）
    cfg = character_service.get(chat.character_id)
    if not character_state.is_enabled(chat.character_id):
        raise HTTPException(status_code=403, detail=f"角色已停用: {cfg.name}")
    _inflight_add([chat.character_id])
    try:
        response = await llm_service.chat_complete(
            message=chat.message,
            history=chat.history,
            character_id=chat.character_id,
        )
        return {
            "reply": response,
            "status": "success",
            "character_id": chat.character_id,
        }
    except HTTPException:
        # 让 FastAPI 自己处理 404 等业务异常（角色不存在等）
        raise
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e),
                "status": "error",
                "character_id": chat.character_id,
            }
        )
    finally:
        _inflight_release([chat.character_id])


class ModelSwitch(BaseModel):
    model: str


@app.get("/api/models")
async def models_endpoint():
    """列出 Ollama 已下载的模型（代理 /api/tags）+ 当前生效模型"""
    import requests as _rq
    try:
        r = _rq.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5)
        names = [m.get("name") for m in r.json().get("models", []) if m.get("name")]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"无法连接 Ollama: {e}")
    return {"models": names, "current": llm_service.overridden_model,
            "preload": llm_service.preload_status()}


@app.post("/api/model")
async def set_model_endpoint(m: ModelSwitch):
    """设置全局模型覆盖（持久化，重启后端自动恢复）并后台预加载新模型"""
    llm_service.set_model(m.model)
    llm_service.start_preload()
    return {"status": "success", "current": llm_service.overridden_model}


# ==================== 动态群聊管理（第五阶段） ====================

@app.get("/api/groups")
async def list_groups():
    """群列表：全部动态群 + 固定群覆盖条目（fixed=true，仅被管理过成员的
    固定群出现，前端据此覆盖 GROUPS 默认成员）；无覆盖的固定群不返回，
    前端用内置 GROUPS，行为与旧版一致。"""
    return {"groups": group_service.list_groups()}


@app.post("/api/groups")
async def create_group(m: GroupCreate):
    """创建群聊：名称非空（≤32 字）、至少一个有效成员（存在且已启用），
    群 ID 服务端安全生成（uuid，用户输入不进路径），不覆盖已有群、
    不影响固定群；成员保序去重。"""
    group = group_service.create_group(m.name, m.members)
    return {"status": "success", "group": group}


@app.post("/api/groups/{group_id}/members")
async def add_group_member(group_id: str, m: GroupMemberAdd):
    """邀请角色入群（动态群或固定群）：群存在（404）、角色存在且已启用
    （400）、不可重复添加（400）；固定群写覆盖条目（不动默认注册表，
    删覆盖即恢复默认）。成功后下一次群聊请求即用最新成员列表，
    不修改历史消息。"""
    return group_service.add_member(group_id, m.member_id)


@app.delete("/api/groups/{group_id}/members/{member_id}")
async def remove_group_member(group_id: str, member_id: str):
    """移除群成员（动态群或固定群）：只改本群成员列表（该角色不再参与
    后续回复），保留其历史消息，不动角色目录/配置/头像/全局启停状态。
    最后一名成员不可移除（400，群内至少保留一人）；固定群写覆盖条目。"""
    return group_service.remove_member(group_id, member_id)


@app.post("/api/groups/{group_id}/name")
async def rename_group(group_id: str, m: GroupRename):
    """修改群名称（第六阶段，仅动态群）：名称去首尾空白、非空（400）、
    ≤32 字（400，与创建一致）；固定群拒绝（400）；不存在的群 404。
    只改本群 name——群 ID 不变（名称只做显示，绝不用于 ID 或文件路径）、
    成员列表/其他群/历史消息不受影响（前端历史按群 ID 存储，原名继续
    显示）；持久化到 groups.json（原子写，写失败回滚内存并返回 500）。"""
    return group_service.rename_group(group_id, m.name)


@app.delete("/api/groups/{group_id}")
async def delete_group(group_id: str):
    """删除群聊（第六阶段，仅动态群）：固定群拒绝（400）；不存在的群
    404（幂等明确——已删除的群再次删除返回 404，与既有约定一致）。
    只删 groups.json 中该群条目（含防御性清理同 ID 覆盖条目）：不动角色
    目录/配置/头像/立绘/背景/TTS/启停状态、不动其他群；写入失败回滚内存
    并返回 500（内存与文件保持一致）。前端群聊历史由前端按群 ID 自行清理。"""
    return group_service.delete_group(group_id)


@app.post("/api/group/chat")
async def group_chat_endpoint(chat: GroupChatMessage):
    """群聊：用户一条消息后，按 members 顺序每个成员依次生成一条回复。

    所有成员共享同一个群聊历史（history + 本轮前面成员的回复），
    但每个成员用各自独立的 character prompt 调用，人格不合并。
    单个成员生成失败不阻断后续成员（文字占位，不进后续上下文）。
    """

    replies = []
    turn_replies = []
    _inflight_add(chat.members)
    try:
        for member_id in chat.members:
            try:
                cfg = character_service.get(member_id)  # 角色不存在时抛 404
            except HTTPException:
                replies.append({"role": member_id, "content": f"⚠️ 成员 {member_id} 不存在", "ok": False})
                continue
            if not character_state.is_enabled(member_id):
                # 停用成员：占位不进后续成员的上下文（与「不存在」同模式），不阻断其他成员
                replies.append({"role": member_id, "content": f"⚠️ {cfg.name} 已停用", "ok": False})
                continue
            try:
                text = await llm_service.group_chat_complete(
                    message=chat.message,
                    history=chat.history,
                    speaker=member_id,
                    turn_replies=turn_replies,
                )
                reply_content = text.strip()
                ok = bool(reply_content)
                if not ok:
                    reply_content = f"⚠️ {cfg.name} 暂时无法回复"
            except Exception:
                reply_content = f"⚠️ {cfg.name} 暂时无法回复"
                ok = False
            # ok=False 的失败占位：前端只显示不写聊天历史，也不进后续成员的上下文
            replies.append({"role": member_id, "content": reply_content, "ok": ok})
            if ok:
                turn_replies.append({"role": member_id, "content": reply_content})
    finally:
        _inflight_release(chat.members)
    return {
        "replies": replies,
        "status": "success",
        "members": chat.members,
    }


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """流式聊天：实时输出每个 chunk"""
    await manager.connect(websocket)
    chat_history = []

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            message = payload.get("message", "")
            character_id = payload.get("character_id", "yuuka")

            await manager.send_personal_message(
                json.dumps({"type": "thinking"}),
                websocket
            )

            full_response = ""
            async for chunk in llm_service.chat_stream(
                message, chat_history, character_id
            ):
                full_response += chunk
                await manager.send_personal_message(
                    json.dumps({"type": "chunk", "content": chunk}),
                    websocket
                )

            chat_history.append({"role": "user", "content": message})
            chat_history.append({"role": "assistant", "content": full_response})

            await manager.send_personal_message(
                json.dumps({
                    "type": "done",
                    "full_response": full_response,
                    "character_id": character_id,
                }),
                websocket
            )

    except WebSocketDisconnect:
        manager.disconnect(websocket)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=True
    )
