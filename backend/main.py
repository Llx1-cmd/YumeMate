from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response
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
from services.tts_service import tts_service

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
    """返回所有可用角色列表（公开信息，不含人设 prompt）"""
    return {"characters": character_service.list_public()}


@app.get("/api/characters/{character_id}")
async def get_character(character_id: str):
    """返回单个角色的公开信息"""
    cfg = character_service.get(character_id)
    return cfg.to_public_dict()


@app.get("/api/characters/{character_id}/avatar")
async def get_character_avatar(character_id: str):
    """返回角色头像文件（前端 <img src=...> 直接用）"""
    cfg = character_service.get(character_id)
    avatar_path = cfg.get_avatar_path()
    if not avatar_path or not avatar_path.exists():
        return JSONResponse(
            status_code=404,
            content={"error": "角色未配置头像"}
        )
    return FileResponse(str(avatar_path))


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
    tts_cfg = cfg.tts
    if not tts_cfg.get("refer_wav_path"):
        return JSONResponse(
            status_code=503,
            content={"error": "该角色未配置语音"},
        )
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
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ==================== 聊天接口 ====================

@app.post("/api/chat")
async def chat_endpoint(chat: ChatMessage):
    """同步聊天：发送消息 + 历史 + character_id，返回完整回复"""
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


@app.post("/api/group/chat")
async def group_chat_endpoint(chat: GroupChatMessage):
    """群聊：用户一条消息后，按 members 顺序每个成员依次生成一条回复。

    所有成员共享同一个群聊历史（history + 本轮前面成员的回复），
    但每个成员用各自独立的 character prompt 调用，人格不合并。
    单个成员生成失败不阻断后续成员（文字占位，不进后续上下文）。
    """
    replies = []
    turn_replies = []
    for member_id in chat.members:
        try:
            cfg = character_service.get(member_id)  # 角色不存在时抛 404
        except HTTPException:
            replies.append({"role": member_id, "content": f"⚠️ 成员 {member_id} 不存在", "ok": False})
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
