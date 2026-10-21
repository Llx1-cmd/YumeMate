import json
import os
import re
import shutil
import warnings
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import HTTPException

# 角色根目录：项目根目录下的 characters/
CHARACTERS_DIR = Path(__file__).parent.parent.parent / "characters"

# 前端立绘/背景资产目录（现有角色立绘仍在此，第四阶段新立绘/背景存角色目录）
FRONTEND_ASSETS_DIR = Path(__file__).parent.parent.parent / "frontend" / "assets"

# 头像文件支持的扩展名（按优先级）
AVATAR_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"]

# 立绘 / 背景文件支持的扩展名（按优先级，第四阶段）
PORTRAIT_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"]
BACKGROUND_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"]

# 头像上传限制：最大 5MB；最长边 / 总像素上限；PIL 格式 -> 落盘扩展名
# （不信任上传文件名，只接受可解码的 PNG/JPEG/WEBP）
MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_EDGE = 4096
MAX_AVATAR_PIXELS = 16_000_000
AVATAR_FORMAT_MAP = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}

# 角色 ID 白名单：仅 ASCII 字母 / 数字 / 下划线 / 连字符，长度 1~32
# （创建新角色时校验；天然拒绝路径穿越与非法字符）
CHARACTER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

# 新角色默认配置（沿用 CharacterConfig 既有字段与默认值，不新增不兼容字段）
DEFAULT_NEW_CHARACTER_MODEL = "qwen2.5:7b-instruct-q4_K_M"
DEFAULT_NEW_CHARACTER_TEMPERATURE = 0.95
DEFAULT_NEW_CHARACTER_TOP_P = 0.9
DEFAULT_NEW_CHARACTER_MAX_TOKENS = 350
DEFAULT_NEW_CHARACTER_COLOR = "#FF6B9D"


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
        # 无背景模式（可选，第四阶段）：配置了 background_color 即该角色
        # 主视图用纯色背景（不回退全局背景图）；未配置则维持现有回退行为
        self.background_color: Optional[str] = data.get("background_color")
        # 语音合成配置（可选）：refer_wav_path/prompt_text/prompt_language/
        # text_language/gpt_model/sovits_model，未配置则该角色无语音
        self.tts: dict = data.get("tts", {}) or {}
        self.prompt: str = prompt
        self.dir_path: Path = dir_path

    def to_public_dict(self) -> dict:
        """返回给前端的公开信息（不含 prompt，避免暴露人设细节）。
        avatar_ver 为头像文件 mtime——前端拼 ?v= 破浏览器缓存，更换头像后
        mtime 变化即得新 URL（无头像为 None）"""
        return {
            "id": self.id,
            "name": self.name,
            "subtitle": self.subtitle,
            "description": self.description,
            "color": self.color,
            "greeting": self.greeting,
            "background_color": self.background_color,
            "has_tts": bool(self.tts.get("refer_wav_path")),
            "avatar_ext": self._get_avatar_ext(),
            "avatar_ver": self._get_avatar_ver(),
        }

    def _get_avatar_ver(self) -> Optional[int]:
        """头像版本号（文件 mtime 秒），无头像返回 None"""
        p = self.get_avatar_path()
        return int(p.stat().st_mtime) if p else None

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

    def _get_portrait_ext(self) -> Optional[str]:
        """返回立绘扩展名（编辑页预览用）：优先规范位置 frontend/assets/
        character/{id}.{ext}（第 66 条统一，与 yuuka/mika 一致），回退
        角色目录 portrait.{ext}（第四阶段旧位置，兼容读取），无返回 None"""
        for ext in PORTRAIT_EXTENSIONS:
            if (FRONTEND_ASSETS_DIR / "character" / f"{self.id}{ext}").exists():
                return ext.lstrip(".")
        for ext in PORTRAIT_EXTENSIONS:
            if (self.dir_path / f"portrait{ext}").exists():
                return ext.lstrip(".")
        return None

    def _get_background_ext(self) -> Optional[str]:
        """返回背景扩展名（编辑页用）：优先规范位置 frontend/assets/
        background/{id}.{ext}（第 66 条统一），回退角色目录
        background.{ext}（旧位置，兼容读取），无背景返回 None"""
        for ext in BACKGROUND_EXTENSIONS:
            if (FRONTEND_ASSETS_DIR / "background" / f"{self.id}{ext}").exists():
                return ext.lstrip(".")
        for ext in BACKGROUND_EXTENSIONS:
            if (self.dir_path / f"background{ext}").exists():
                return ext.lstrip(".")
        return None


class CharacterService:
    """角色加载服务：启动时扫描 characters/ 目录，加载所有角色配置"""

    def __init__(self):
        self._characters: Dict[str, CharacterConfig] = {}
        # 每个角色目录的发现/加载诊断（供 /api/characters/health 报告）：
        # {目录名: {"loaded": bool, "error": str or None}}
        self.discovery: Dict[str, dict] = {}
        self.load_all()

    def load_all(self) -> None:
        """扫描 characters/ 目录，加载所有角色（单个角色损坏不影响其他角色）"""
        self._characters.clear()
        self.discovery = {}
        if not CHARACTERS_DIR.exists():
            print(f"[CharacterService] 角色目录不存在: {CHARACTERS_DIR}")
            return

        for sub in CHARACTERS_DIR.iterdir():
            if not sub.is_dir():
                continue
            if sub.name.startswith("."):
                # 隐藏目录（如删除操作的 .deleting-* 暂存目录）不参与角色扫描，
                # 防止删除中的角色目录被重新加载回内存
                continue
            try:
                cfg = self._load_one(sub)
                self._characters[cfg.id] = cfg
                self.discovery[sub.name] = {"loaded": True, "error": None}
                print(f"[CharacterService] 已加载角色: {cfg.id} ({cfg.name})")
            except Exception as e:
                self.discovery[sub.name] = {
                    "loaded": False, "error": f"{type(e).__name__}: {e}",
                }
                print(f"[CharacterService] 加载失败 {sub.name}: {e}")

    def _load_one(self, dir_path: Path) -> CharacterConfig:
        """加载单个角色目录；配置缺失/损坏抛异常（load_all 捕获并记录诊断，
        不影响其他角色加载）"""
        json_path = dir_path / "character.json"
        prompt_path = dir_path / "prompt.txt"

        if not json_path.exists():
            raise FileNotFoundError("缺少 character.json")
        if not prompt_path.exists():
            raise FileNotFoundError("缺少 prompt.txt")

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

    def is_loaded(self, character_id: str) -> bool:
        """角色是否已成功加载进内存（健康检查/诊断用）"""
        return character_id in self._characters

    def get_avatar_path(self, character_id: str) -> Optional[Path]:
        """取某个角色的头像文件路径"""
        return self.get(character_id).get_avatar_path()

    # ==================== 角色配置编辑（第三阶段） ====================

    def reload_one(self, character_id: str) -> CharacterConfig:
        """从磁盘重新加载单个角色并更新内存缓存（其他角色不动）。

        供配置编辑保存后调用：llm_service 每次聊天都经 character_service.get()
        取 prompt/参数，reload 后后续聊天即用新配置，无需改 llm 主流程。
        重新加载失败（文件被并发改坏等）抛异常，内存保留旧配置。
        """
        cfg = self._characters.get(character_id)
        if not cfg:
            raise HTTPException(status_code=404, detail=f"角色不存在: {character_id}")
        new_cfg = self._load_one(cfg.dir_path)
        self._characters[character_id] = new_cfg
        return new_cfg

    def add_loaded(self, dir_path: Path) -> CharacterConfig:
        """加载指定目录的角色并加入内存缓存（其他角色不动）。

        供角色创建成功后调用：目录已完整（character.json + prompt.txt），
        加载失败（磁盘故障等）抛异常由调用方清理该目录。
        """
        cfg = self._load_one(dir_path)
        self._characters[cfg.id] = cfg
        self.discovery[dir_path.name] = {"loaded": True, "error": None}
        return cfg

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        """原子写文本：先写同目录临时文件再 os.replace，失败时目标文件保留原样。
        统一 LF 换行（现有 character.json / prompt.txt 均为 LF）。"""
        tmp = path.with_name(path.name + ".tmp-write")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(tmp, path)
        except Exception as e:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise HTTPException(
                status_code=500,
                detail=f"写入文件失败（{type(e).__name__}），原文件未改动",
            )

    def update_profile(self, character_id: str, name: str, description: str) -> dict:
        """编辑角色名称与简介：写回 character.json（保留其他字段原样），
        原子替换 + 重载内存。名称去首尾空白且禁止为空。"""
        cfg = self.get(character_id)  # 不存在抛 404
        name = (name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="角色名称不能为空")
        json_path = cfg.dir_path / "character.json"
        if not json_path.exists():
            raise HTTPException(
                status_code=400, detail="角色配置文件缺失（character.json）"
            )
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("顶层应为 JSON 对象")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"当前配置文件无法解析（{type(e).__name__}），请先修复后再编辑",
            )
        data["name"] = name
        data["description"] = (description or "").strip()
        self._atomic_write_text(
            json_path, json.dumps(data, ensure_ascii=False, indent=2)
        )
        new_cfg = self.reload_one(character_id)
        return new_cfg.to_public_dict()

    def update_prompt(self, character_id: str, prompt: str) -> dict:
        """编辑人设提示词：写 prompt.txt（原文写入，保留换行与中英日字符），
        原子替换后重新读取校验内容一致，再重载内存。禁止空提示词。"""
        cfg = self.get(character_id)
        if not (prompt or "").strip():
            raise HTTPException(status_code=400, detail="提示词不能为空")
        prompt = (prompt or "").replace("\r\n", "\n")
        path = cfg.dir_path / "prompt.txt"
        self._atomic_write_text(path, prompt)
        with open(path, "r", encoding="utf-8") as f:
            reread = f.read()
        if reread != prompt:
            raise HTTPException(
                status_code=500,
                detail="保存后校验失败：重新读取的内容与保存内容不一致，请重试",
            )
        new_cfg = self.reload_one(character_id)
        return {"name": new_cfg.name, "prompt_length": len(new_cfg.prompt)}

    @staticmethod
    def _validate_image(data: bytes) -> str:
        """头像图片校验（更换头像 / 创建角色共用）：校验通过返回落盘扩展名。

        - 大小 ≤ 5MB；像素尺寸：最长边 ≤ 4096 且总像素 ≤ 1600 万（解码前
          读 header 中的 size 拒绝，避免解码超大图耗内存）；
        - 解压炸弹防护：把 PIL 的 DecompressionBombWarning 升级为异常、
          DecompressionBombError 直接捕获，两者均 400 拒绝；
        - PIL 完整解码校验，坏文件 400 拒绝；
        - 扩展名由图片实际格式决定（不信任上传文件名），仅 PNG/JPG/WEBP。"""
        if not data:
            raise HTTPException(status_code=400, detail="图片内容为空")
        if len(data) > MAX_AVATAR_BYTES:
            raise HTTPException(
                status_code=400, detail=f"图片过大（超过 {MAX_AVATAR_BYTES // 1024 // 1024}MB）"
            )
        try:
            from PIL import Image  # 环境已随 Streamlit/GPT-SoVITS 提供，不新增依赖
        except ImportError:
            raise HTTPException(
                status_code=500, detail="后端缺少 Pillow，无法校验图片"
            )
        try:
            with warnings.catch_warnings():
                # 炸弹防护：warning 升级为异常（Error 本身就是异常），
                # 确保 PIL 发出 DecompressionBombWarning 的图片被拒绝
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                img = Image.open(BytesIO(data))
                fmt = img.format
                # 解码前先按 header 中的 size 拒绝超大图（此时像素未加载）
                w, h = img.size
                if max(w, h) > MAX_AVATAR_EDGE or w * h > MAX_AVATAR_PIXELS:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"图片尺寸过大（{w}×{h}，要求最长边不超过 "
                            f"{MAX_AVATAR_EDGE} 像素且总像素不超过 "
                            f"{MAX_AVATAR_PIXELS // 10000} 万）"
                        ),
                    )
                img.verify()  # 完整解码校验，坏文件抛异常
        except HTTPException:
            raise
        except Exception as e:
            if isinstance(
                e, (Image.DecompressionBombError, Image.DecompressionBombWarning)
            ):
                raise HTTPException(
                    status_code=400, detail="图片像素数过大（疑似解压炸弹），已拒绝"
                )
            raise HTTPException(
                status_code=400, detail="文件不是有效的图片（无法解码）"
            )
        ext = AVATAR_FORMAT_MAP.get(fmt)
        if not ext:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的图片格式 {fmt}（仅支持 PNG / JPG / WEBP）",
            )
        return ext

    def update_avatar(self, character_id: str, data: bytes) -> dict:
        """更换角色头像：校验（大小 / 像素尺寸 / PIL 可解码 / 格式白名单）
        后写入 characters/{id}/avatar.{ext}。

        - 与创建角色共用 _validate_image 校验规则（见其注释）；
        - 若与现有头像扩展名不同，先移开旧文件再替换（否则 get_avatar_path
          按优先级仍会命中旧文件）；旧文件先改名备份，任一步失败回滚恢复；
        - 写入路径全部由服务端拼接到该角色目录内，天然拒绝路径穿越。"""
        cfg = self.get(character_id)
        ext = self._validate_image(data)

        dir_path = cfg.dir_path
        target = dir_path / f"avatar{ext}"
        tmp = dir_path / f"avatar{ext}.tmp-write"
        # 现有头像（白名单扩展名）先改名备份；.tmp-write/.bak 后缀不在
        # AVATAR_EXTENSIONS 内，不会被 get_avatar_path 误取
        olds = [
            p for p in dir_path.glob("avatar.*")
            if p.suffix in AVATAR_EXTENSIONS and p != target
        ]
        backups = []
        try:
            tmp.write_bytes(data)
            for old in olds:
                bak = old.with_name(old.name + ".bak")
                old.rename(bak)
                backups.append((bak, old))
            os.replace(tmp, target)
        except Exception as e:
            # 回滚：恢复所有已挪走的旧文件，清掉临时文件，目标保持原状
            for bak, old in backups:
                try:
                    if bak.exists() and not old.exists():
                        bak.rename(old)
                except OSError:
                    pass
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise HTTPException(
                status_code=500,
                detail=f"头像写入失败（{type(e).__name__}），原头像未改动",
            )

        # 成功：清掉备份（换格式时旧扩展名头像到此才真正移除）
        for bak, _ in backups:
            try:
                if bak.exists():
                    bak.unlink()
            except OSError:
                pass
        new_cfg = self.reload_one(character_id)
        return {"name": new_cfg.name, "avatar_ext": new_cfg._get_avatar_ext()}

    # ==================== 角色创建 / 删除（第四阶段） ====================

    def create_character(
        self,
        character_id: str,
        name: str,
        prompt: str,
        description: str = "",
        subtitle: str = "",
        avatar_data: Optional[bytes] = None,
        portrait_data: Optional[bytes] = None,
        background_data: Optional[bytes] = None,
        background_copy_from: Optional[str] = None,
        background_color: Optional[str] = None,
    ) -> CharacterConfig:
        """创建新角色：服务端独立校验后写 characters/{id}/（character.json +
        prompt.txt + 可选 avatar），可选立绘/背景写 frontend/assets/（第 66 条
        统一规范位置，与 yuuka/mika 现有角色一致），全部成功才加载进内存。

        - ID：CHARACTER_ID_RE 白名单（ASCII 字母/数字/下划线/连字符，1~32 位），
          天然拒绝路径穿越；目录路径由服务端拼接到 characters/ 直接子目录；
        - 拒绝空名称 / 空提示词 / 重复 ID / 已存在角色目录（无论是否加载成功）；
        - character.json 沿用现有字段结构 + 默认值（subtitle 可选写入，与
          yuuka/mika 字段结构一致；不新增不兼容字段），不写 tts（可选配置，
          未配置则无语音，健康检查 tts_ok=None 不算异常）；
        - 立绘（portrait_data）写 frontend/assets/character/{id}.{ext}
          （规范位置，未提供则该位置留空，不指向其他角色文件）；
        - 背景三选一（互斥，最多给一个）：background_data（上传，写
          frontend/assets/background/{id}.{ext}）/ background_copy_from
          （复制已存在背景，"default" 或角色 id，复制文件不改其他角色）/
          background_color（无背景模式，写入 character.json 的
          background_color 字段，主视图纯色）；全不提供则不写背景（前端
          回退全局默认背景，与现有角色一致）；
        - 失败时清理本次新建的目录与本次写入的 assets 文件（不误删原有文件）。
        """
        character_id = (character_id or "").strip()
        name = (name or "").strip()
        prompt = (prompt or "").replace("\r\n", "\n")
        description = (description or "").strip()
        subtitle = (subtitle or "").strip()
        background_color = (background_color or "").strip()
        if not CHARACTER_ID_RE.match(character_id or ""):
            raise HTTPException(
                status_code=400,
                detail=(
                    "角色 ID 只能包含英文字母、数字、下划线和连字符"
                    "（长度 1~32），不能包含空格、中文或其他字符"
                ),
            )
        if not name:
            raise HTTPException(status_code=400, detail="角色名称不能为空")
        if not prompt.strip():
            raise HTTPException(status_code=400, detail="提示词不能为空")
        if character_id in self._characters:
            raise HTTPException(
                status_code=400, detail=f"角色 ID 已存在: {character_id}"
            )
        # 背景三选一：上传 / 复用已存在 / 无背景（颜色），互斥
        bg_choices = [
            ("上传背景", background_data is not None),
            ("复用已存在背景", bool(background_copy_from)),
            ("无背景颜色", bool(background_color)),
        ]
        chosen = [n for n, v in bg_choices if v]
        if len(chosen) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"背景配置只能三选一（上传 / 复用已存在 / 无背景颜色），"
                f"同时给了：{'、'.join(chosen)}",
            )
        if background_color and not re.match(r"^#[0-9A-Fa-f]{6}$|^#[0-9A-Fa-f]{3}$", background_color):
            raise HTTPException(
                status_code=400, detail="背景颜色格式非法（应为 #RRGGBB 或 #RGB）"
            )
        dir_path = (CHARACTERS_DIR / character_id).resolve()
        # 双保险：即使 id 校验被绕过，目录也必须落在 characters/ 直接子目录内
        if dir_path.parent != CHARACTERS_DIR.resolve():
            raise HTTPException(status_code=400, detail="角色目录路径非法")
        if dir_path.exists():
            raise HTTPException(
                status_code=400,
                detail=f"角色目录已存在（不会被覆盖）: {character_id}",
            )
        # 复用背景：先校验来源存在并拿到源文件（目录创建前校验，失败不建目录）
        source_bg = None
        if background_copy_from:
            source_bg = self._find_background_file(background_copy_from.strip())
        dir_path.mkdir()
        written_assets: list = []
        try:
            config = {
                "id": character_id,
                "name": name,
                "subtitle": subtitle,
                "description": description,
                "model": DEFAULT_NEW_CHARACTER_MODEL,
                "temperature": DEFAULT_NEW_CHARACTER_TEMPERATURE,
                "top_p": DEFAULT_NEW_CHARACTER_TOP_P,
                "max_tokens": DEFAULT_NEW_CHARACTER_MAX_TOKENS,
                "color": DEFAULT_NEW_CHARACTER_COLOR,
                "greeting": f"你好，我是{name}，很高兴认识你。",
            }
            if background_color:
                config["background_color"] = background_color
            self._atomic_write_text(
                dir_path / "character.json",
                json.dumps(config, ensure_ascii=False, indent=2),
            )
            self._atomic_write_text(dir_path / "prompt.txt", prompt)
            if avatar_data is not None:
                ext = self._validate_image(avatar_data)
                (dir_path / f"avatar{ext}").write_bytes(avatar_data)
            # 立绘/背景写规范位置 assets/（第 66 条统一）：_replace_image_file
            # 复用（含旧格式清理与备份回滚），目录不存在时先创建
            if portrait_data is not None:
                ext = self._validate_image(portrait_data)
                assets_char = FRONTEND_ASSETS_DIR / "character"
                assets_char.mkdir(parents=True, exist_ok=True)
                self._replace_image_file(
                    assets_char, character_id, ext, portrait_data,
                    PORTRAIT_EXTENSIONS, "立绘",
                )
                written_assets.append(assets_char / f"{character_id}{ext}")
            assets_bg = FRONTEND_ASSETS_DIR / "background"
            if background_data is not None:
                ext = self._validate_image(background_data)
                assets_bg.mkdir(parents=True, exist_ok=True)
                self._replace_image_file(
                    assets_bg, character_id, ext, background_data,
                    BACKGROUND_EXTENSIONS, "背景",
                )
                written_assets.append(assets_bg / f"{character_id}{ext}")
            if source_bg is not None:
                assets_bg.mkdir(parents=True, exist_ok=True)
                self._replace_image_file(
                    assets_bg, character_id, source_bg.suffix,
                    source_bg.read_bytes(), BACKGROUND_EXTENSIONS, "背景",
                )
                written_assets.append(assets_bg / f"{character_id}{source_bg.suffix}")
        except Exception:
            # 失败清理：目录为本次新建（上面已校验不存在），只删本次文件；
            # assets 侧同样只删本次写入的文件（_replace_image_file 失败时
            # 自身已回滚，不会留下半写状态）
            shutil.rmtree(dir_path, ignore_errors=True)
            for p in written_assets:
                try:
                    if p.exists():
                        p.unlink()
                except OSError:
                    pass
            raise
        return self.add_loaded(dir_path)

    @staticmethod
    def _find_background_file(source: str) -> Path:
        """查找背景来源文件（复制用）：source="default"（全局默认背景）或
        角色 id（该角色当前实际使用的背景：规范位置 assets/background/
        {id}.{ext} → 角色目录旧位置 → 全局默认，逐级回退，与前端
        get_background 同规则）。找不到抛 400。"""
        if source == "default":
            for name in ("background.jpg", "background.png", "background.jpeg"):
                p = FRONTEND_ASSETS_DIR / "background" / name
                if p.exists():
                    return p
            raise HTTPException(status_code=400, detail="默认背景文件不存在")
        if not CHARACTER_ID_RE.match(source):
            raise HTTPException(status_code=400, detail=f"背景来源非法: {source}")
        # 来源角色必须真实存在（404）
        cfg = character_service.get(source)
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            p = FRONTEND_ASSETS_DIR / "background" / f"{source}{ext}"
            if p.exists():
                return p
        for ext in BACKGROUND_EXTENSIONS:
            p = cfg.dir_path / f"background{ext}"
            if p.exists():
                return p
        for name in ("background.jpg", "background.png", "background.jpeg"):
            p = FRONTEND_ASSETS_DIR / "background" / name
            if p.exists():
                return p
        raise HTTPException(
            status_code=400, detail=f"角色 {source} 没有可复用的背景文件"
        )

    def delete_character(self, character_id: str) -> dict:
        """删除角色：先 rename 到 .deleting-* 隐藏目录（原子操作，任一后续
        步骤失败目录都不在原地、不参与重扫），再清内存缓存与发现诊断，最后
        rmtree 删除暂存目录，并同步清理 assets 规范位置的立绘/背景（第 66 条
        统一后角色资源分散两处，删除需一并清理，避免孤儿文件被同 ID 重建的
        角色意外继承）。

        - 返回 {"name": 角色名, "cleanup_warning": 残留提示 or None}：
          rmtree 失败（如 Windows 文件被占用）时角色已从列表与内存移除、
          状态一致（.deleting-* 不参与扫描），残留目录由 warning 提示；
        - assets 清理只删 {id}.{ext} 精确匹配文件（服务端拼接，无 glob），
          不触碰其他角色文件；失败并入 warning 提示，不影响删除结果；
        - 不存在抛 404；启用状态记录由调用方（路由层）另行清理。
        """
        cfg = self.get(character_id)  # 不存在抛 404
        dir_path = cfg.dir_path
        # 防穿越：目标必须是 characters/ 的直接子目录（resolve 后仍校验）
        if dir_path.resolve().parent != CHARACTERS_DIR.resolve():
            raise HTTPException(
                status_code=400, detail="目标不是合法的角色目录，拒绝删除"
            )
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        trash = CHARACTERS_DIR / f".deleting-{character_id}-{stamp}"
        try:
            dir_path.rename(trash)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"角色目录占用中，删除失败（{type(e).__name__}），原目录未改动",
            )
        name = cfg.name
        # rename 已成功：清理内存缓存与发现诊断（角色从列表消失，重扫不会回来）
        self._characters.pop(character_id, None)
        self.discovery.pop(dir_path.name, None)
        cleanup_warning = None
        try:
            shutil.rmtree(trash)
        except Exception as e:
            cleanup_warning = (
                f"角色已删除并停用，但部分文件暂存于 characters/.deleting-{character_id}-{stamp}"
                f"（{type(e).__name__}），不影响使用，可稍后手动清理"
            )
        # 第 66 条：清理 assets 规范位置的立绘/背景（角色资源随角色删除）
        for subdir, extensions in (
            ("character", PORTRAIT_EXTENSIONS),
            ("background", BACKGROUND_EXTENSIONS),
        ):
            for ext in extensions:
                p = FRONTEND_ASSETS_DIR / subdir / f"{character_id}{ext}"
                try:
                    if p.exists():
                        p.unlink()
                except Exception as e:
                    extra = (
                        f"资产文件未能清理: frontend/assets/{subdir}/"
                        f"{character_id}{ext}（{type(e).__name__}），可手动删除"
                    )
                    cleanup_warning = (
                        f"{cleanup_warning}；{extra}" if cleanup_warning else extra
                    )
        return {"name": name, "cleanup_warning": cleanup_warning}

    # ==================== 立绘 / 背景更换（第四阶段补充） ====================

    @staticmethod
    def _replace_image_file(dir_path: Path, stem: str, ext: str, data: bytes,
                            whitelist, what: str) -> None:
        """写图片文件并移开同 stem 的旧格式文件（portrait/background 共用，
        与 update_avatar 同模式）：临时文件 → 备份旧文件 → 原子替换 → 清备份，
        任一步失败回滚恢复旧文件、目标保持原状。"""
        target = dir_path / f"{stem}{ext}"
        tmp = dir_path / f"{stem}{ext}.tmp-write"
        olds = [
            p for p in dir_path.glob(f"{stem}.*")
            if p.suffix in whitelist and p != target
        ]
        backups = []
        try:
            tmp.write_bytes(data)
            for old in olds:
                bak = old.with_name(old.name + ".bak")
                old.rename(bak)
                backups.append((bak, old))
            os.replace(tmp, target)
        except Exception as e:
            for bak, old in backups:
                try:
                    if bak.exists() and not old.exists():
                        bak.rename(old)
                except OSError:
                    pass
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise HTTPException(
                status_code=500,
                detail=f"{what}写入失败（{type(e).__name__}），原文件未改动",
            )
        for bak, _ in backups:
            try:
                if bak.exists():
                    bak.unlink()
            except OSError:
                pass

    def _set_json_fields(self, cfg: CharacterConfig, updates: dict) -> None:
        """更新 character.json 的指定字段（v=None 表示删除该字段，
        保留其他字段原样），原子替换。"""
        json_path = cfg.dir_path / "character.json"
        if not json_path.exists():
            raise HTTPException(
                status_code=400, detail="角色配置文件缺失（character.json）"
            )
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("顶层应为 JSON 对象")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"当前配置文件无法解析（{type(e).__name__}），请先修复后再编辑",
            )
        for k, v in updates.items():
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v
        self._atomic_write_text(
            json_path, json.dumps(data, ensure_ascii=False, indent=2)
        )

    def _write_image_to_assets(
        self, cfg: CharacterConfig, subdir: str, stem: str, data: bytes,
        ext: str, whitelist, what: str,
    ) -> None:
        """写图片到规范位置 frontend/assets/{subdir}/{id}{ext}（第 66 条统一，
        与 yuuka/mika 一致），并清走角色目录 {stem}.* 旧位置残留（读取端
        角色目录优先级更高，不清会盖住新写入的规范位置文件）。

        残留先 rename 成 *.replacing 暂存：assets 写入失败时恢复原状
        （_replace_image_file 自带回滚），成功后删除暂存；删除失败的
        .replacing 残留不在扩展名白名单内，不会被读取逻辑误取，无害。"""
        assets_dir = FRONTEND_ASSETS_DIR / subdir
        assets_dir.mkdir(parents=True, exist_ok=True)
        leftovers = [
            p for p in cfg.dir_path.glob(f"{stem}.*")
            if p.suffix in whitelist
        ]
        moved = []
        try:
            for p in leftovers:
                tmp = p.with_name(p.name + ".replacing")
                p.rename(tmp)
                moved.append((tmp, p))
            self._replace_image_file(assets_dir, cfg.id, ext, data, whitelist, what)
        except Exception:
            for tmp, orig in moved:
                try:
                    if tmp.exists() and not orig.exists():
                        tmp.rename(orig)
                except OSError:
                    pass
            raise
        for tmp, _ in moved:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    def update_portrait(self, character_id: str, data: bytes) -> dict:
        """更换角色立绘：校验（_validate_image，与头像同规则）后写规范位置
        frontend/assets/character/{id}.{ext}（第 66 条统一），换格式时移开
        旧立绘（备份回滚）；角色目录残留的第四阶段旧位置 portrait.{ext}
        一并清走（写入路径全部由服务端拼接到合法目录内）。"""
        cfg = self.get(character_id)
        ext = self._validate_image(data)
        self._write_image_to_assets(
            cfg, "character", "portrait", data, ext, PORTRAIT_EXTENSIONS, "立绘"
        )
        return {"name": cfg.name, "portrait_ext": ext.lstrip(".")}

    def update_background(
        self, character_id: str, image_data: Optional[bytes] = None,
        copy_from: Optional[str] = None, color: Optional[str] = None,
    ) -> dict:
        """更换角色背景（三选一互斥，全回滚保证）：

        - image_data：上传，写规范位置 frontend/assets/background/{id}.{ext}
          （第 66 条统一，清 background_color 字段——背景图优先于纯色模式）；
        - copy_from："default" 或角色 id，复制该背景文件为本角色专属
          （不改其他角色文件，清 background_color 字段）；
        - color：hex，写 character.json 的 background_color 字段（无背景
          模式，删除两处旧背景文件——残留无害，bg_color 优先级更高）。
        """
        cfg = self.get(character_id)
        choices = [
            ("上传背景", image_data is not None),
            ("复用已存在背景", bool(copy_from)),
            ("无背景颜色", bool(color)),
        ]
        chosen = [n for n, v in choices if v]
        if not chosen:
            raise HTTPException(
                status_code=400,
                detail="请选择一种背景配置（上传 / 复用已存在 / 纯色）",
            )
        if len(chosen) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"背景配置只能三选一（上传 / 复用已存在 / 纯色），"
                f"同时给了：{'、'.join(chosen)}",
            )
        if color:
            color = color.strip()
            if not re.match(r"^#[0-9A-Fa-f]{6}$|^#[0-9A-Fa-f]{3}$", color):
                raise HTTPException(
                    status_code=400, detail="背景颜色格式非法（应为 #RRGGBB 或 #RGB）"
                )
        source_bg = self._find_background_file(copy_from.strip()) if copy_from else None

        if color:
            # 纯色模式：先写 background_color（bg_color 优先级高于背景文件），
            # 再尽力删除两处旧背景文件（删除失败残留无害）
            self._set_json_fields(cfg, {"background_color": color})
            for p in cfg.dir_path.glob("background.*"):
                if p.suffix in BACKGROUND_EXTENSIONS:
                    try:
                        p.unlink()
                    except OSError:
                        pass
            for ext in BACKGROUND_EXTENSIONS:
                p = FRONTEND_ASSETS_DIR / "background" / f"{character_id}{ext}"
                try:
                    if p.exists():
                        p.unlink()
                except OSError:
                    pass
            self.reload_one(character_id)
            return {"name": cfg.name, "background_color": color}

        # 上传 / 复用：写（复制）背景文件到规范位置 + 清 background_color 字段
        if image_data is not None:
            ext = self._validate_image(image_data)
            data = image_data
        else:
            ext = source_bg.suffix
            data = source_bg.read_bytes()
        self._write_image_to_assets(
            cfg, "background", "background", data, ext, BACKGROUND_EXTENSIONS, "背景"
        )
        if cfg.background_color:
            self._set_json_fields(cfg, {"background_color": None})
        self.reload_one(character_id)
        return {"name": cfg.name, "background_ext": ext.lstrip(".")}


character_service = CharacterService()
