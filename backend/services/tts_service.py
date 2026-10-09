import hashlib
import time
import requests
from pathlib import Path
from config import settings

# 语音缓存目录（临时文件 + 自动清理，不无限积累）
TTS_CACHE_DIR = Path(__file__).parent.parent.parent / "cache" / "tts"
TTS_CACHE_MAX_AGE = 6 * 3600   # 超过 6 小时的缓存音频自动删除
TTS_CACHE_MAX_FILES = 60       # 最多保留 60 个缓存音频

# 项目根目录（character.json 里 tts 路径的相对基准；GPT-SoVITS 是独立进程，
# 收到相对路径会按它自己的工作目录解析，必须先转成绝对路径再传）
PROJECT_ROOT = Path(__file__).parent.parent.parent


def _resolve_path(p: str) -> str:
    """把 character.json 里的 tts 路径解析为绝对路径：已是绝对路径原样返回，
    相对路径按项目根解析（这样仓库 clone 到任何机器/盘符都能直接跑）"""
    path = Path(p)
    if path.is_absolute():
        return p
    return str((PROJECT_ROOT / p).resolve())

# 中文 → 日语 翻译用的 system prompt（一次性调用，不带聊天历史）
TRANSLATE_SYSTEM_PROMPT = (
    "你是翻译引擎。把用户给的中文聊天回复翻译成自然、口语化的日语。"
    "规则：只输出日语译文本身；不要输出中文、解释、注音或任何其他内容；"
    "角色对「老师」的称呼译为「先生」。"
)


class TTSService:
    """GPT-SoVITS 语音合成服务：中文回复 → 日语文本 → 角色语音（WAV）

    调用的是本机 GPT-SoVITS api.py (v1)：
    - GET  /?text=&text_language=&refer_wav_path=&prompt_text=&prompt_language=  → WAV 流
    - POST /set_model  切换权重（可选，角色未配置权重路径则跳过）
    参考音频等参数逐请求传入，不依赖 API 端状态，天然支持多角色。
    """

    def __init__(self):
        self.base_url = "http://127.0.0.1:9880"
        self._loaded_weights = None  # 本进程内已通过 /set_model 设置的权重（避免重复加载）

    # ---- 状态 ----
    def available(self) -> bool:
        """GPT-SoVITS API 是否在线（收到任意 HTTP 响应即算在线）"""
        try:
            requests.get(f"{self.base_url}/", timeout=2)
            return True
        except requests.exceptions.RequestException:
            return False

    # ---- 权重 ----
    def _ensure_weights(self, tts_cfg: dict) -> None:
        """确保 API 当前加载该角色配置的权重；未配置权重路径则使用 API 现有权重"""
        gpt = _resolve_path(tts_cfg.get("gpt_model", ""))
        sovits = _resolve_path(tts_cfg.get("sovits_model", ""))
        if not gpt or not sovits:
            return
        want = (gpt, sovits)
        if self._loaded_weights == want:
            return
        r = requests.post(
            f"{self.base_url}/set_model",
            json={"gpt_model_path": gpt, "sovits_model_path": sovits},
            timeout=120,
        )
        if r.status_code != 200 or r.json().get("code") != 0:
            raise RuntimeError(f"set_model 失败: {r.text[:200]}")
        self._loaded_weights = want

    # ---- 中文 → 日语 ----
    def translate(self, text: str, model: str) -> str:
        """用 Ollama 把中文回复翻译成日语文本（独立请求，不影响聊天上下文）"""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 300},
        }
        r = requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=120,
        )
        r.raise_for_status()
        ja = (r.json().get("message", {}).get("content") or "").strip()
        # 去掉模型可能加的包裹符号
        while ja[:1] in ("「", "\"", "“") and ja[-1:] in ("」", "\"", "”"):
            ja = ja[1:-1].strip()
        if not ja:
            raise RuntimeError("翻译结果为空")
        return ja

    # ---- 合成 ----
    def synthesize(self, character_id: str, tts_cfg: dict, model: str, text: str) -> bytes:
        """完整链路：中文 → 日语 → GPT-SoVITS WAV（带文件缓存，相同文本不重复生成）"""
        key = hashlib.sha1(f"{character_id}|{text}".encode("utf-8")).hexdigest()
        cache_file = TTS_CACHE_DIR / f"{character_id}_{key}.wav"

        if cache_file.exists():
            return cache_file.read_bytes()

        self._ensure_weights(tts_cfg)
        ja_text = self.translate(text, model)

        r = requests.get(
            f"{self.base_url}/",
            params={
                "text": ja_text,
                "text_language": tts_cfg.get("text_language", "ja"),
                "refer_wav_path": _resolve_path(tts_cfg["refer_wav_path"]),
                "prompt_text": tts_cfg["prompt_text"],
                "prompt_language": tts_cfg.get("prompt_language", "ja"),
            },
            timeout=180,
        )
        if r.status_code != 200:
            raise RuntimeError(f"GPT-SoVITS 返回 {r.status_code}: {r.text[:200]}")
        wav = r.content
        if len(wav) < 1000:
            raise RuntimeError(f"GPT-SoVITS 返回的音频异常（{len(wav)} 字节）")

        # 写缓存 + 清理旧缓存
        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(wav)
        self._cleanup_cache()
        return wav

    def _cleanup_cache(self):
        """删除过期/超量的缓存音频，避免无限积累"""
        now = time.time()
        files = sorted(TTS_CACHE_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        for i, p in enumerate(files):
            if i >= TTS_CACHE_MAX_FILES or (now - p.stat().st_mtime) > TTS_CACHE_MAX_AGE:
                try:
                    p.unlink()
                except OSError:
                    pass


tts_service = TTSService()
