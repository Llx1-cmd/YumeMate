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


class ChatMessage(BaseModel):
    message: str
    history: List[Dict] = []
    character_id: str = "yuuka"


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
            cfg.to_full_dict()["model"],  # 翻译复用角色配置的 Ollama 模型
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
