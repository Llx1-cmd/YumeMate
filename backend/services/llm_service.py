import aiohttp
import json
from datetime import datetime
from typing import AsyncGenerator
from config import settings
from services.character_service import character_service


class LLMService:
    """LLM 调用服务：根据 character_id 取对应人设和参数调用 Ollama"""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL

    @staticmethod
    def _time_context() -> str:
        """每次请求动态生成当前现实时间上下文（仅注入 system prompt，不进 history）"""
        now = datetime.now().astimezone()
        weekday = "星期" + "一二三四五六日"[now.weekday()]
        h = now.hour
        if 5 <= h <= 8:
            period = "清晨"
        elif 9 <= h <= 11:
            period = "上午"
        elif 12 <= h <= 13:
            period = "中午"
        elif 14 <= h <= 17:
            period = "下午"
        elif 18 <= h <= 21:
            period = "晚上"
        else:
            period = "深夜"
        return (
            "【当前现实时间】\n"
            f"日期：{now.year}年{now.month}月{now.day}日\n"
            f"时间：{now.strftime('%H:%M')}\n"
            f"星期：{weekday}\n"
            f"时间段：{period}\n"
            "\n"
            "【时间使用规则】\n"
            "- 你知道当前现实时间。\n"
            "- 历史对话里任何人提到的任何时间都可能已过期，一律忽略；当前时间只以本提示的【当前现实时间】为准。\n"
            "- 只有当当前时间与用户的话题、行为、角色状态或当前情境有关时，才自然地参考时间。\n"
            "- 不要机械地在每条回复中提到时间。\n"
            "- 不要主动汇报当前日期或时间，除非用户询问或者时间对当前话题确实有意义。\n"
            "- 用户问时间时，直接引用【当前现实时间】里的时间数字，不要自行推算或四舍五入。\n"
            "- 不要因为知道当前时间，就强行改变当前话题。\n"
            "- 如果时间与当前对话无关，就自然聊天，不需要提及时间。"
        )

    async def chat_stream(
        self,
        message: str,
        history: list = None,
        character_id: str = "yuuka",
    ) -> AsyncGenerator[str, None]:
        # 从角色服务拿配置；角色不存在时 character_service 会抛 404
        cfg = character_service.get(character_id)
        char_cfg = cfg.to_full_dict()

        # 构造 messages：先 system（角色人设 + 动态现实时间），再历史，最后当前用户消息
        effective_prompt = char_cfg["prompt"] + "\n\n" + self._time_context()
        messages = [{"role": "system", "content": effective_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        payload = {
            "model": char_cfg["model"],
            "messages": messages,
            "stream": True,
            "temperature": char_cfg["temperature"],
            "top_p": char_cfg["top_p"],
            "max_tokens": char_cfg["max_tokens"],
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                async for line in response.content:
                    if line:
                        try:
                            data = json.loads(line.decode("utf-8"))
                            if data.get("message", {}).get("content"):
                                yield data["message"]["content"]
                        except json.JSONDecodeError:
                            continue

    async def chat_complete(
        self,
        message: str,
        history: list = None,
        character_id: str = "yuuka",
    ) -> str:
        full_response = ""
        async for chunk in self.chat_stream(message, history, character_id):
            full_response += chunk
        return full_response


llm_service = LLMService()
