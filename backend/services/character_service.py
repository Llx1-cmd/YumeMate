import json
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import HTTPException

# 角色根目录：项目根目录下的 characters/
CHARACTERS_DIR = Path(__file__).parent.parent.parent / "characters"

# 头像文件支持的扩展名（按优先级）
AVATAR_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"]


class CharacterConfig:
    """单个角色的完整配置（含 prompt）"""

    def __init__(self, data: dict, prompt: str, dir_path: Path):
        self.id: str = data["id"]
        self.name: str = data.get("name", self.id)
        self.subtitle: str = data.get("subtitle", "")
        self.description: str = data.get("description", "")
        self.model: str = data.get("model", "qwen2.5:7b-instruct-q4_K_M")
        self.temperature: float = data.get("temperature", 0.95)
        self.top_p: float = data.get("top_p", 0.9)
        self.max_tokens: int = data.get("max_tokens", 350)
        self.color: str = data.get("color", "#FF6B9D")
        self.greeting: str = data.get("greeting", "")
        # 语音合成配置（可选）：refer_wav_path/prompt_text/prompt_language/
        # text_language/gpt_model/sovits_model，未配置则该角色无语音
        self.tts: dict = data.get("tts", {}) or {}
        self.prompt: str = prompt
        self.dir_path: Path = dir_path

    def to_public_dict(self) -> dict:
        """返回给前端的公开信息（不含 prompt，避免暴露人设细节）"""
        return {
            "id": self.id,
            "name": self.name,
            "subtitle": self.subtitle,
            "description": self.description,
            "color": self.color,
            "greeting": self.greeting,
            "has_tts": bool(self.tts.get("refer_wav_path")),
            "avatar_ext": self._get_avatar_ext(),
        }

    def to_full_dict(self) -> dict:
        """返回完整信息（供 LLM 调用使用）"""
        return {
            "id": self.id,
            "name": self.name,
            "model": self.model,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "prompt": self.prompt,
        }

    def get_avatar_path(self) -> Optional[Path]:
        """返回头像文件的绝对路径，找不到返回 None"""
        for ext in AVATAR_EXTENSIONS:
            p = self.dir_path / f"avatar{ext}"
            if p.exists():
                return p
        return None

    def _get_avatar_ext(self) -> Optional[str]:
        """返回头像扩展名（用于前端拼 URL），无头像返回 None"""
        for ext in AVATAR_EXTENSIONS:
            if (self.dir_path / f"avatar{ext}").exists():
                return ext.lstrip(".")
        return None


class CharacterService:
    """角色加载服务：启动时扫描 characters/ 目录，加载所有角色配置"""

    def __init__(self):
        self._characters: Dict[str, CharacterConfig] = {}
        self.load_all()

    def load_all(self) -> None:
        """扫描 characters/ 目录，加载所有角色"""
        self._characters.clear()
        if not CHARACTERS_DIR.exists():
            print(f"[CharacterService] 角色目录不存在: {CHARACTERS_DIR}")
            return

        for sub in CHARACTERS_DIR.iterdir():
            if not sub.is_dir():
                continue
            try:
                cfg = self._load_one(sub)
                if cfg:
                    self._characters[cfg.id] = cfg
                    print(f"[CharacterService] 已加载角色: {cfg.id} ({cfg.name})")
            except Exception as e:
                print(f"[CharacterService] 加载失败 {sub.name}: {e}")

    def _load_one(self, dir_path: Path) -> Optional[CharacterConfig]:
        """加载单个角色目录"""
        json_path = dir_path / "character.json"
        prompt_path = dir_path / "prompt.txt"

        if not json_path.exists():
            print(f"[CharacterService] 跳过 {dir_path.name}: 缺少 character.json")
            return None
        if not prompt_path.exists():
            print(f"[CharacterService] 跳过 {dir_path.name}: 缺少 prompt.txt")
            return None

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt = f.read()

        # 如果 json 没填 id，用目录名兜底
        if "id" not in data:
            data["id"] = dir_path.name

        return CharacterConfig(data, prompt, dir_path)

    def list_public(self) -> List[dict]:
        """返回所有角色的公开信息列表（给前端展示用）"""
        return [c.to_public_dict() for c in self._characters.values()]

    def get(self, character_id: str) -> CharacterConfig:
        """按 id 取单个角色完整配置；找不到抛 404"""
        cfg = self._characters.get(character_id)
        if not cfg:
            raise HTTPException(
                status_code=404,
                detail=f"角色不存在: {character_id}"
            )
        return cfg

    def get_avatar_path(self, character_id: str) -> Optional[Path]:
        """取某个角色的头像文件路径"""
        return self.get(character_id).get_avatar_path()


character_service = CharacterService()
