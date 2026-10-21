import json
import shutil
from datetime import datetime
from pathlib import Path

from services.character_service import (
    CHARACTERS_DIR,
    AVATAR_EXTENSIONS,
    character_service,
)

DATA_DIR = Path(__file__).parent.parent / "data"
STATE_FILE = DATA_DIR / "character_state.json"
# 项目根目录：character.json 里的 TTS 路径是相对路径（相对项目根，与
# tts_service._resolve_path 同规则），存在性检查按此解析
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 必需字段：角色配置的最小集合（缺失记入诊断 issues）
REQUIRED_FIELDS = ["id", "name", "model"]
# TTS 配置字段完整性（配置了 tts 时应齐全；异常只记录不阻止文字聊天）
TTS_FIELDS = [
    "refer_wav_path", "prompt_text", "prompt_language",
    "text_language", "gpt_model", "sovits_model",
]


class CharacterStateService:
    """角色启用状态（独立 JSON 状态文件，不改 character.json/prompt.txt）
    + 配置健康检查。

    状态文件格式：{"enabled": {"角色id": true/false}}
    只存显式记录：无记录的角色默认启用（新角色开箱即用）。
    """

    def __init__(self):
        self.corrupt_backup = None
        self.corrupt_error = None

    def _load(self) -> dict:
        """读启用状态；文件缺失=无记录（全默认启用）。

        文件损坏时不静默覆盖/重置用户状态：先把原文备份为带时间戳的
        .corrupt-<时间戳> 文件（用户数据保留，可手工检查/恢复），本次读取
        以「全默认启用」安全回退，损坏详情经 diagnose()/health_report() 报告。
        """
        self.corrupt_backup = None
        self.corrupt_error = None
        if not STATE_FILE.exists():
            return {"enabled": {}}
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("顶层应为 JSON 对象")
            enabled = data.get("enabled", {})
            if not isinstance(enabled, dict):
                raise ValueError("enabled 字段应为 JSON 对象")
            return {"enabled": enabled}
        except Exception as e:
            self.corrupt_error = f"{type(e).__name__}: {e}"
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = STATE_FILE.with_name(f"character_state.json.corrupt-{stamp}")
            try:
                shutil.copy2(STATE_FILE, backup)
                self.corrupt_backup = backup
            except Exception as be:
                self.corrupt_error += f"；备份失败: {be}"
            return {"enabled": {}}

    def is_enabled(self, character_id: str) -> bool:
        """角色是否启用：无状态记录默认启用；状态文件损坏时安全回退默认启用"""
        return bool(self._load()["enabled"].get(character_id, True))

    def set_enabled(self, character_id: str, enabled: bool) -> dict:
        """设置启用状态并持久化；返回状态文件诊断（含损坏提示，供接口展示）。

        若原状态文件损坏：此时已备份原文，写入新状态是用户主动操作，
        不丢失用户数据（备份文件保留）。
        """
        state = self._load()
        enabled_map = dict(state.get("enabled", {}))
        enabled_map[character_id] = bool(enabled)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"enabled": enabled_map}, f, ensure_ascii=False, indent=2)
        return self.diagnose()

    def remove_record(self, character_id: str) -> None:
        """删除角色的启用状态记录（角色删除后调用，防止状态文件残留）。

        状态文件缺失时无需清理；删除失败（磁盘故障）仅抛出由调用方处理，
        本方法本身不阻断删除流程（残留记录只影响「默认启用」语义，
        角色目录已删，无实际影响）。
        """
        if not STATE_FILE.exists():
            return
        state = self._load()
        enabled_map = dict(state.get("enabled", {}))
        if character_id not in enabled_map:
            return
        enabled_map.pop(character_id, None)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"enabled": enabled_map}, f, ensure_ascii=False, indent=2)

    def diagnose(self) -> dict:
        """状态文件健康诊断（损坏时返回备份路径与原因，供 health_report 报告）"""
        self._load()
        return {
            "ok": self.corrupt_error is None,
            "error": self.corrupt_error,
            "corrupt_backup": str(self.corrupt_backup) if self.corrupt_backup else None,
            "path": str(STATE_FILE),
        }

    def health_report(self) -> dict:
        """全部角色配置健康检查（纯文件系统 + JSON 解析，不调 Ollama 生成、
        不合成语音）。

        「已发现」（characters/ 目录存在）/「配置检查通过」（config_ok）
        /「已启用」（enabled）三层分开表示；TTS 配置异常只记录 tts_ok=False，
        不阻止纯文字聊天；单个角色损坏只影响自己的诊断条目。
        """
        report = {"state_file": self.diagnose(), "characters": []}
        if not CHARACTERS_DIR.exists():
            report["characters_error"] = f"角色目录不存在: {CHARACTERS_DIR}"
            return report
        enabled_map = self._load()["enabled"]

        for sub in sorted(CHARACTERS_DIR.iterdir()):
            if not sub.is_dir():
                continue
            if sub.name.startswith("."):
                # 隐藏目录（.deleting-* 删除暂存）不参与健康检查（与 load_all 一致）
                continue
            entry = {
                "dir": sub.name,
                "id": None,
                "discovered": True,
                "loaded": False,
                "config_ok": False,
                "prompt_ok": False,
                "avatar_ok": False,
                "tts_ok": None,
                "enabled": None,
                "issues": [],
            }

            # ---- character.json 存在性与解析 ----
            data = None
            json_path = sub / "character.json"
            if not json_path.exists():
                entry["issues"].append("缺少 character.json")
            else:
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        raise ValueError("顶层应为 JSON 对象")
                except Exception as e:
                    entry["issues"].append(
                        f"character.json 解析失败: {type(e).__name__}: {e}"
                    )

            # ---- 必需字段 + 模型字段完整性 ----
            if data is not None:
                missing = [
                    k for k in REQUIRED_FIELDS if not str(data.get(k) or "").strip()
                ]
                for k in missing:
                    entry["issues"].append(f"缺少必需字段: {k}")
                entry["config_ok"] = not missing
                entry["id"] = str(data.get("id") or "").strip() or sub.name

                # ---- TTS 配置完整性（可选：未配置=None，异常=False）----
                tts = data.get("tts")
                if not tts:
                    entry["tts_ok"] = None
                else:
                    tts_issues = [
                        f"TTS 配置缺少字段: {k}" for k in TTS_FIELDS
                        if not str(tts.get(k) or "").strip()
                    ]
                    for key in ("refer_wav_path", "gpt_model", "sovits_model"):
                        v = str(tts.get(key) or "").strip()
                        p = Path(v)
                        if v and not p.is_absolute():
                            p = PROJECT_ROOT / v
                        if v and not p.exists():
                            tts_issues.append(f"TTS 文件不存在: {key}={v}")
                    entry["issues"].extend(tts_issues)
                    entry["tts_ok"] = not tts_issues

            # ---- 提示词文件 ----
            prompt_path = sub / "prompt.txt"
            if not prompt_path.exists():
                entry["issues"].append("缺少 prompt.txt")
            else:
                try:
                    with open(prompt_path, "r", encoding="utf-8") as f:
                        if f.read().strip():
                            entry["prompt_ok"] = True
                        else:
                            entry["issues"].append("prompt.txt 内容为空")
                except Exception as e:
                    entry["issues"].append(f"prompt.txt 读取失败: {type(e).__name__}: {e}")

            # ---- 头像文件 ----
            avatar_ok = any(
                (sub / f"avatar{ext}").exists() for ext in AVATAR_EXTENSIONS
            )
            entry["avatar_ok"] = avatar_ok
            if not avatar_ok:
                entry["issues"].append("缺少头像文件（avatar.png/jpg/jpeg/webp）")

            # ---- 加载与启用状态（分开表示）----
            entry["loaded"] = character_service.is_loaded(entry["id"])
            entry["enabled"] = bool(enabled_map.get(entry["id"], True))

            report["characters"].append(entry)
        return report


character_state = CharacterStateService()