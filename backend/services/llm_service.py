import aiohttp
import asyncio
import json
import os
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import AsyncGenerator
from config import settings
from services.character_service import character_service


class LLMService:
    """LLM 调用服务：根据 character_id 取对应人设和参数调用 Ollama"""

    # 群聊单条回复的生成上限：只允许一条自然回复（一到两句 ~100 token），
    # 限制多轮模拟的空间，也加速生成
    GROUP_MAX_TOKENS = 150

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        # 前端「模型切换」的覆盖模型（持久化到 backend/data/model_state.json，
        # 重启后端自动恢复上次选择；None = 使用各角色 character.json 的默认模型）
        self.overridden_model = None
        self._state_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "model_state.json",
        )
        self._load_state()
        # 模型预加载：后台任务 + 状态快照（供 /api/models 查询与前端展示）
        self._preload_task = None
        self._preload_state = {"model": None, "status": "idle", "detail": ""}

    # ---------- 模型选择持久化（唯一状态源仍是 overridden_model） ----------

    def _load_state(self):
        """启动时恢复上次选择的模型（文件缺失/损坏 = 从未选择，静默用默认）"""
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                self.overridden_model = (json.load(f).get("model") or "").strip() or None
        except Exception:
            self.overridden_model = None

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump({"model": self.overridden_model}, f, ensure_ascii=False)
        except Exception as e:
            print(f"[LLMService] 模型状态持久化失败: {e}")

    def set_model(self, model):
        """设置全局模型覆盖并持久化（None = 恢复各角色默认）"""
        self.overridden_model = (model or "").strip() or None
        self._save_state()

    def effective_model_now(self):
        """当前生效的全局模型（覆盖优先；未覆盖时取角色默认，作为预加载目标）"""
        if self.overridden_model:
            return self.overridden_model
        try:
            for c in character_service.list_public():
                cfg = character_service.get(c["id"]).to_full_dict()
                return cfg.get("model")
        except Exception:
            pass
        return None

    # ---------- 模型预加载（生命周期管理） ----------

    def preload_status(self):
        return dict(self._preload_state)

    def start_preload(self):
        """后台预加载当前生效模型（快速连续切换时取消过时任务，防止竞争）"""
        if self._preload_task and not self._preload_task.done():
            self._preload_task.cancel()
        self._preload_task = asyncio.ensure_future(self._preload_model())

    async def _loaded_models(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/ps",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    data = await r.json()
                    return [m.get("name") for m in data.get("models", [])]
        except Exception:
            return []

    async def _unload_model(self, model):
        """卸载指定模型（keep_alive=0；不主动打断进行中的生成）"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json={"model": model, "keep_alive": 0},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as r:
                    await r.read()
            print(f"[LLMService] 已请求卸载模型 {model}（切换腾出显存）")
        except Exception as e:
            print(f"[LLMService] 卸载模型 {model} 失败（不阻断后续加载）: {e}")

    async def _preload_model(self):
        """预加载目标模型：空 prompt 只加载不生成，keep_alive=-1 常驻。

        已加载则跳过（FastAPI 重启后不重复加载）；
        8GB 显存放不下两个 8b 模型，加载前先卸载其他常驻模型。
        """
        target = self.effective_model_now()
        if not target:
            self._preload_state = {"model": None, "status": "idle", "detail": "未配置模型"}
            return
        self._preload_state = {"model": target, "status": "loading", "detail": "预加载中"}
        print(f"[LLMService] 模型预加载开始: {target}")
        try:
            loaded = await self._loaded_models()
            if target in loaded:
                self._preload_state = {
                    "model": target, "status": "ok", "detail": "已在内存，无需重复加载",
                }
                print(f"[LLMService] 模型 {target} 已在内存，跳过预加载")
                return
            for m in loaded:
                if m != target:
                    await self._unload_model(m)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json={"model": target, "prompt": "", "keep_alive": -1},
                    timeout=aiohttp.ClientTimeout(total=600),
                ) as r:
                    if r.status != 200:
                        body = await r.text()
                        raise RuntimeError(f"Ollama HTTP {r.status}: {body[:200]}")
                    await r.read()
            # 以 /api/ps 确认结果，不把「请求已发出」当作「加载完成」
            loaded = await self._loaded_models()
            if target in loaded:
                self._preload_state = {
                    "model": target, "status": "ok", "detail": "预加载完成，模型常驻内存",
                }
                print(f"[LLMService] 模型预加载成功: {target}（keep_alive=-1 常驻）")
            else:
                self._preload_state = {
                    "model": target, "status": "failed",
                    "detail": "加载请求完成但模型未驻留内存",
                }
                print(f"[LLMService] 模型预加载异常: {target} 请求完成但未驻留")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._preload_state = {"model": target, "status": "failed", "detail": str(e)}
            print(f"[LLMService] 模型预加载失败: {target} -> {e}")


    def _effective_model(self, char_cfg):
        """当前生效模型：前端覆盖优先，否则用该角色 character.json 的默认模型"""
        return self.overridden_model or char_cfg["model"]

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
            "- 结合当前时间段理解老师的场景：深夜（23点后）提到吃饭指夜宵、清晨提到吃饭指早餐、中午指午餐；"
            "时间只是背景信息，不要因为时间段就主动把话题转向休息、睡觉或劝老师休息，更不要无缘无故说晚安。\n"
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
            "model": self._effective_model(char_cfg),
            "messages": messages,
            "stream": True,
            "temperature": char_cfg["temperature"],
            "top_p": char_cfg["top_p"],
            "max_tokens": char_cfg["max_tokens"],
            "think": False,
            "keep_alive": -1,
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

    def _speaker_name(self, role_id: str) -> str:
        """群聊历史里的角色 id → 显示名（角色已不存在时用 id 兜底）"""
        try:
            return character_service.get(role_id).name
        except Exception:
            return role_id

    @staticmethod
    def _group_note(my_name: str) -> str:
        """群聊回复规则（精简重组：4 条覆盖输出纪律 + 意图优先级 + 防重复/立场）"""
        return (
            "【群聊回复规则（必须严格遵守）】\n"
            f"1. 你只以「{my_name}」的身份说话，严格保持自己的人格与说话风格；"
            "只输出你自己的台词本身（一到两句），输出后立即停止。\n"
            "2. 群聊记录里的「[名字]：」前缀是系统标注其他成员发言用的；"
            "绝对禁止输出任何说话人标签、替其他成员说话、或生成多轮对话/剧本。\n"
            "3. 当前用户的新问题拥有最高优先级，回复前先判断它的意图：\n"
            "- 老师征求建议、要求推荐、帮忙或出主意时——先给出你的具体内容"
            "（具体的地点、方案、做法），如果有必要再在最后补一句询问；"
            "不要先反问偏好或条件再等老师回答。\n"
            "- 老师问「你们」「各自」的经历、感受或情况时——先回答你自己的部分，"
            "再考虑是否反问；不要用反问老师来代替回答。\n"
            "- 有质疑、纠正或澄清时，以最新澄清后的意图为准：先理解老师在质疑/澄清什么，"
            "再解释或修正——不要重复刚才的话，不要把话题拉回旧问题或之前反复出现的内容。\n"
            "- 判断不出明确意图时，就自然地回应当前对话。\n"
            "4. 禁止复用自己之前轮次中已经表达过、没有必要再重复的内容；"
            "回应其他成员可以，但回应不等于重复；被问观点或偏好时，"
            "按你自己的性格给出真实倾向，不要为了稳妥而中立和稀泥，"
            "也不要把对方刚说的观点原样复述成自己的；老师切换话题时立即跟随新话题。"
        )

    def _group_speaker_pattern(self) -> str:
        """群聊 speaker label 的正则候选：全部角色全名 + 名（name[-2:]）+ id + 老师。

        模型违规输出的 label 形式多样（[早濑优香]：/[优香]：/优香：/Yuuka:），逐一覆盖。
        """
        names = {"老师", "teacher"}
        try:
            for c in character_service.list_public():
                names.add(c["id"])
                names.add(c["name"])
                if len(c["name"]) >= 2:
                    names.add(c["name"][-2:])
        except Exception:
            pass
        return "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))

    def _sanitize_group_reply(self, text: str) -> str:
        """群聊回复防护清理（生成层兜底，不依赖模型自觉）：

        1) 剥掉模型违规输出的开头 speaker label（[优香]：/优香：/Yuuka: 等）；
        2) 截断模型模拟的多轮对话——正文中间再出现任何 speaker label 即截断
           （正常聊天回复不会以「名字：」开头或在句中内嵌「名字：」）。
        """
        text = (text or "").strip()
        if not text:
            return text
        pat = self._group_speaker_pattern()
        head_re = re.compile(rf'^\[?\s*(?:{pat})\s*\]?\s*[：:]\s*')
        text = head_re.sub("", text, count=1).strip()
        mid_re = re.compile(rf'[\n\r]+\s*\[?\s*(?:{pat})\s*\]?\s*[：:]')
        m = mid_re.search(text)
        if m:
            text = text[:m.start()].rstrip()
        return text.strip()

    @staticmethod
    def _norm_text(s: str) -> str:
        """复读判定用文本归一化：去空白与常见中英文标点/语气符号"""
        return re.sub(
            r"[\s，。！？!?.,~～、「」『』()（）♪…·:：;；'\"“”‘’]+", "", s or ""
        )

    def _is_echo(self, new: str, refs: list) -> bool:
        """复读检测（生成层兜底，不依赖模型自觉）：

        新回复与任一参照文本（自己上一条 / 其他成员最后一条 / 本轮前面成员）
        归一化后逐字相同、互为长子串或相似度≥0.85，判定为复读。
        0.85 而非 0.9：实测「删掉开头半句式复读」约 0.87，而重组转述/换说法的
        正常回应实测均 <0.75——0.85 恰好分隔两者，只拦复读不拦正常重组。
        """
        n = self._norm_text(new)
        if len(n) < 8:
            return False
        for ref in refs:
            r = self._norm_text(ref)
            if len(r) < 12:
                continue
            if n == r or r in n or n in r:
                return True
            if SequenceMatcher(None, n, r).ratio() >= 0.85:
                return True
        return False

    @staticmethod
    def _echo_refs(history: list, speaker: str, turn_replies: list = None) -> list:
        """复读参照文本：该角色在历史里最近一条 + 其他成员在历史里最近一条
        + 本轮已生成的其他成员回复（一次性多成员调用时由 turn_replies 传入）。"""
        last_self = None
        last_other = None
        for m in history or []:
            role = m.get("role")
            if role == "user" or not m.get("content"):
                continue
            if role == speaker:
                last_self = m["content"]
            else:
                last_other = m["content"]
        refs = [x for x in (last_self, last_other) if x]
        refs += [m.get("content", "") for m in (turn_replies or [])]
        return refs

    async def group_chat_stream(
        self,
        message: str,
        history: list = None,
        speaker: str = "yuuka",
        turn_replies: list = None,
        anti_echo: int = 0,
    ) -> AsyncGenerator[str, None]:
        """群聊流式生成：共享群聊历史（渲染成 user 侧「群聊记录」文本）+ 该角色独立人格。

        消息结构（根治多轮模仿）：每次请求都是 system + 单条 user，assistant 位置
        永远只有模型自己的回复——历史里的成员台词以「[名字]：」纯文本行进入群聊记录
        （不是 assistant 格式），模型无从「续写剧本」。当前角色人格只来自其
        character prompt，不与他人合并。
        turn_replies 是本轮排在 speaker 之前、已生成完的其他成员回复（一次性
        多成员调用时使用；分步调用恒空，历史里已含之前成员回复）。
        anti_echo 是复读重试级别：1=user 任务追加正向引导（不展示被复读原句
        全文——负向禁令+展示全文反而诱发逐字复制）；2=再把 speaker 自己最近
        一条历史行替换为占位标注（防重复靠结构：锚点原文不在 transcript 里
        就无从逐字复制；仅本次生成的临时视图，不改真实历史）。
        """
        cfg = character_service.get(speaker)
        char_cfg = cfg.to_full_dict()
        my_name = char_cfg["name"]

        # 第 2 级重试：定位 speaker 自己最近一条历史消息（占位替换的锚点）
        self_last = None
        if anti_echo >= 2:
            for m in history or []:
                if m.get("role") == speaker and m.get("content"):
                    self_last = m["content"]

        def _line(m: dict) -> str:
            if m.get("role") == "user":
                return f"老师：{m.get('content', '')}"
            name = self._speaker_name(m.get("role", ""))
            if (
                self_last is not None
                and m.get("role") == speaker
                and m.get("content") == self_last
            ):
                return (
                    f"[{name}]：（这句发言老师已经听到了，不需要再说一遍，"
                    "老师现在在等你说新的内容）"
                )
            return f"[{name}]：{m.get('content', '')}"

        lines = [_line(m) for m in (history or [])]
        lines += [_line(m) for m in (turn_replies or [])]
        transcript = "\n".join(lines) if lines else "（还没有人发言）"

        # 时间上下文放 system 末尾（离生成位置最近、注意力最强）；
        # 群聊记录作为背景放 system（远端），user 位置只放当前新问题——
        # 生成位置附近只有当前问题，小模型注意力不被历史稀释（防复用旧回复）
        effective_prompt = (
            char_cfg["prompt"] + "\n\n" + self._group_note(my_name)
            + "\n\n【群聊记录（背景资料，仅供理解上下文）】\n" + transcript
            + "\n\n" + self._time_context()
        )
        now = datetime.now()
        user_content = (
            f"【当前用户的新问题（最高优先级，只回答这个）】\n{message}\n\n"
            f"【你的任务】\n"
            f"先判断这条新问题在问什么，再按下面的顺序回答：\n"
            f"- 老师提出问题时，先回答问题本身。\n"
            f"- 老师问「你们」「各自」或询问你的个人经历、感受时，先回答你自己的部分。\n"
            f"- 老师征求建议、要求推荐、帮忙或出主意时，先给出至少一个具体建议，"
            f"不要先反问偏好并等待回答；如果群里已有成员就这个问题给出了具体建议，"
            f"就提出一个不同的想法，或从你自己的角度给出新的补充。\n"
            f"- 回答完之后再自然地反问老师（可选）；反问不能排在回答之前，也不能代替回答。\n"
            f"不要拉回旧话题或复用之前说过的内容。"
            f"现在时间是 {now.strftime('%H:%M')}，请结合当前时间段理解老师的场景。"
            f"以「{my_name}」的身份输出一到两句台词本身即可，"
            f"不要名字前缀、不要替其他成员说话、不要模拟多轮对话。"
        )
        if anti_echo >= 1:
            user_content += (
                "\n\n【重要提示】\n"
                "你刚才准备的回答和群聊记录里已有的发言重复了，需要重新回答。"
                "老师现在想听的是新的内容：如果老师在追问理由或原因，"
                "就讲出你自己的理由和考量；如果老师在等建议，就给出你自己的想法。"
                "就算要表达相近的意思，也必须换一种新的说法，"
                "不要把记录里出现过的句子再说一遍。"
            )
        if anti_echo >= 2:
            user_content += (
                "\n（你在群聊记录里最近那句发言已被标注：老师已经听到过了，"
                "请针对老师的最新消息说出新的回应。）"
            )
        messages = [
            {"role": "system", "content": effective_prompt},
            {"role": "user", "content": user_content},
        ]

        payload = {
            "model": self._effective_model(char_cfg),
            "messages": messages,
            "stream": True,
            "temperature": char_cfg["temperature"],
            "top_p": char_cfg["top_p"],
            "max_tokens": min(char_cfg["max_tokens"], self.GROUP_MAX_TOKENS),
            "think": False,
            "keep_alive": -1,
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

    async def group_chat_complete(
        self,
        message: str,
        history: list = None,
        speaker: str = "yuuka",
        turn_replies: list = None,
    ) -> str:
        async def _once(anti_echo: int) -> str:
            full = ""
            async for chunk in self.group_chat_stream(
                message, history, speaker, turn_replies, anti_echo=anti_echo
            ):
                full += chunk
            # 生成层防护清理：剥 speaker label 前缀 + 截断多轮模拟
            return self._sanitize_group_reply(full)

        text = await _once(0)
        # 复读兜底：与「自己上一条/其他成员最后一条」逐字级重复时逐级重试
        # （1=正向指令；2=指令+把自己锚点句占位替换；纯提示词路线已被实测
        # 证伪：正向引导只降频、负向禁令无效，追问场景 6/6 逐字复读）。
        # 每次重试后复检，通过即返回；全部失败则接受最后一次结果，不无限重试。
        refs = self._echo_refs(history, speaker, turn_replies)
        if text and self._is_echo(text, refs):
            for attempt in (1, 2):
                print(f"[LLMService] 群聊复读检测触发({speaker})，重试 {attempt}/2")
                retry = await _once(attempt)
                if retry and not self._is_echo(retry, refs):
                    return retry
                if retry:
                    text = retry
        return text

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
