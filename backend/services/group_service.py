# -*- coding: utf-8 -*-
"""动态群聊服务（第五阶段）+ 固定群成员管理（第 68 条）。

设计要点：
- 群数据存 backend/data/groups.json（独立状态文件，不动角色/固定群任何文件），
  原子写（tmp + replace），损坏时备份回退为空（与 character_state 同模式）；
- 动态群 ID 由服务端安全生成（"g_" + uuid4 hex 前 12 位），用户输入的群名称
  只做显示用，绝不进入文件路径或作为内部 ID（天然拒绝路径穿越）；
- 固定群（FIXED_GROUPS 注册表，与前端 GROUPS 同步）不迁移：默认成员兜底，
  成员变更存 groups.json 覆盖条目（fixed=true），删除覆盖即恢复默认；
  名称恒以注册表为准（兼容）；ID/成员管理 API 与动态群共用；
- 成员校验全部服务端独立做：角色存在（character_service.get 404）+ 已启用
  （character_state.is_enabled，停用/无效角色不得成为有效成员）；
- 邀请追加（保序去重，禁止重复添加）；移除只改本群成员列表，不动角色目录、
  配置、头像、全局启停状态，也不动任何群聊历史（历史在前端 session，按
  group_id 隔离，本服务不触碰）；最后一名成员不可移除（空群无意义）。
"""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from services.character_service import character_service
from services.character_state import character_state

DATA_DIR = Path(__file__).parent.parent / "data"
GROUPS_FILE = DATA_DIR / "groups.json"

GROUP_ID_PREFIX = "g_"
GROUP_ID_LEN = 14  # "g_" + 12 位 hex
GROUP_NAME_MAX = 32
MEMBERS_MAX = 8

# 固定群注册表（第 68 条）：与前端 streamlit_app.py 的 GROUPS 保持同步——
# 后端需认识固定群 ID 才能对其做成员管理校验（邀请/移除）。固定群不迁移：
# 默认成员是兜底，成员变更存为 groups.json 里的「覆盖条目」（带 fixed=true），
# 删除覆盖条目即恢复默认；名称始终以本表为准（兼容要求）。
FIXED_GROUPS = {
    "yuuka_mika": {
        "name": "优香 × 未花",
        "members": ["yuuka", "mika"],
    },
}


class GroupService:
    """群组管理：动态群 {group_id: {...}} + 固定群成员覆盖 {gid: {..., fixed}}"""

    def __init__(self):
        self._groups: dict = {}
        # 固定群成员覆盖（第 68 条）：仅当固定群被管理过成员后才存在；
        # 无覆盖时固定群用 FIXED_GROUPS 默认成员，前端行为与旧版完全一致
        self._fixed_overrides: dict = {}
        self._load()

    # ==================== 持久化 ====================

    def _load(self) -> None:
        """加载 groups.json（损坏时备份回退为空，不影响启动）。
        条目分流：id 在 FIXED_GROUPS → 固定群覆盖；g_ 前缀 → 动态群；
        其他 id 忽略（无法识别，防幽灵群混入列表）。"""
        if not GROUPS_FILE.exists():
            return
        try:
            with open(GROUPS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("顶层应为 JSON 对象")
            groups = {}
            overrides = {}
            for gid, g in data.items():
                if not isinstance(g, dict) or not isinstance(gid, str):
                    continue
                members = g.get("members")
                if (not isinstance(g.get("name"), str)
                        or not isinstance(members, list)
                        or not all(isinstance(m, str) for m in members)):
                    continue
                if gid in FIXED_GROUPS:
                    # 固定群覆盖：名称以 FIXED_GROUPS 为准（兼容，不受文件内容影响）
                    overrides[gid] = {
                        "id": gid,
                        "name": FIXED_GROUPS[gid]["name"],
                        "members": list(dict.fromkeys(members)),
                        "created_at": g.get("created_at", ""),
                        "fixed": True,
                    }
                elif gid.startswith(GROUP_ID_PREFIX):
                    groups[gid] = {
                        "id": gid,
                        "name": g.get("name", ""),
                        "members": list(dict.fromkeys(members)),
                        "created_at": g.get("created_at", ""),
                    }
            self._groups = groups
            self._fixed_overrides = overrides
        except Exception as e:
            backup = GROUPS_FILE.with_name(
                GROUPS_FILE.name + f".corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            )
            try:
                GROUPS_FILE.rename(backup)
                print(f"[GroupService] 群数据文件损坏（{type(e).__name__}），"
                      f"已备份为 {backup.name}，回退为空群列表")
            except Exception:
                print(f"[GroupService] 群数据文件损坏且备份失败（{type(e).__name__}）")
            self._groups = {}
            self._fixed_overrides = {}

    def _save(self) -> None:
        """原子写 groups.json（tmp + replace，失败抛 500 由路由层转译）。
        动态群 + 固定群覆盖条目合并写入。"""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = GROUPS_FILE.with_name(GROUPS_FILE.name + ".tmp-write")
        merged = dict(self._groups)
        merged.update(self._fixed_overrides)
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            tmp.replace(GROUPS_FILE)
        except Exception as e:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise HTTPException(
                status_code=500,
                detail=f"群数据保存失败（{type(e).__name__}），操作未生效",
            )

    # ==================== 查询 ====================

    def list_groups(self) -> list:
        """全部动态群 + 固定群覆盖条目（按创建时间排序）。
        固定群仅在被管理过成员后（存在覆盖）才出现在列表里（条目带
        fixed=true）；无覆盖时不出——前端用 GROUPS 默认成员，旧版兼容。"""
        entries = list(self._groups.values()) + list(self._fixed_overrides.values())
        return sorted(entries, key=lambda g: g.get("created_at", ""))

    def get_group(self, group_id: str) -> dict:
        """取单个群（动态群或固定群），不存在抛 404。

        固定群返回副本（fixed=true）：成员 = 覆盖 or FIXED_GROUPS 默认；
        名称恒为 FIXED_GROUPS 注册的名称（兼容——不受文件内容影响）。"""
        g = self._groups.get(group_id)
        if g:
            return g
        if group_id in FIXED_GROUPS:
            base = FIXED_GROUPS[group_id]
            override = self._fixed_overrides.get(group_id)
            return {
                "id": group_id,
                "name": base["name"],
                "members": list(override["members"]) if override else list(base["members"]),
                "created_at": (override or {}).get("created_at", ""),
                "fixed": True,
            }
        raise HTTPException(status_code=404, detail=f"群聊不存在: {group_id}")

    # ==================== 校验 ====================

    @staticmethod
    def _validate_member(member_id: str) -> None:
        """成员必须是存在且已启用的角色（不存在 400 / 停用 400）"""
        member_id = (member_id or "").strip()
        if not re.match(r"^[A-Za-z0-9_-]{1,32}$", member_id or ""):
            raise HTTPException(status_code=400, detail=f"无效的角色 ID: {member_id!r}")
        try:
            cfg = character_service.get(member_id)
        except HTTPException:
            raise HTTPException(
                status_code=400,
                detail=f"角色不存在，无法作为群成员: {member_id}",
            )
        if not character_state.is_enabled(member_id):
            raise HTTPException(
                status_code=400,
                detail=f"角色「{cfg.name}」已停用，无法加入群聊（可在角色管理中启用）",
            )

    def _new_group_id(self) -> str:
        """生成不重复的安全群 ID（uuid hex，与用户输入无关）"""
        while True:
            gid = GROUP_ID_PREFIX + uuid.uuid4().hex[:GROUP_ID_LEN - 2]
            if gid not in self._groups:
                return gid

    # ==================== 创建 / 邀请 / 移除 ====================

    def create_group(self, name: str, members: list) -> dict:
        """创建群聊：名称非空（去首尾空白，≤32 字符）、成员非空且全部为
        存在+启用的有效角色（保序去重）；群 ID 服务端生成保证不与已有群
        重复，也不影响前端固定群。"""
        name = (name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="群聊名称不能为空")
        if len(name) > GROUP_NAME_MAX:
            raise HTTPException(
                status_code=400, detail=f"群聊名称过长（最多 {GROUP_NAME_MAX} 字）"
            )
        if not isinstance(members, list) or not members:
            raise HTTPException(status_code=400, detail="至少选择一个角色作为初始成员")
        if not all(isinstance(m, str) for m in members):
            raise HTTPException(status_code=400, detail="成员列表格式非法")
        # 保序去重（重复提交同一角色只算一个）
        members = list(dict.fromkeys(m.strip() for m in members if (m or "").strip()))
        if not members:
            raise HTTPException(status_code=400, detail="至少选择一个角色作为初始成员")
        if len(members) > MEMBERS_MAX:
            raise HTTPException(
                status_code=400, detail=f"群成员过多（最多 {MEMBERS_MAX} 人）"
            )
        for m in members:
            self._validate_member(m)
        gid = self._new_group_id()
        group = {
            "id": gid,
            "name": name,
            "members": members,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._groups[gid] = group
        self._save()
        return group

    def add_member(self, group_id: str, member_id: str) -> dict:
        """邀请角色入群（动态群或固定群）：群存在（404）、角色存在+启用
        （400）、不重复（400）。成功后追加到成员列表末尾（下一次群聊请求
        即用最新列表）；固定群写入覆盖条目（不动 FIXED_GROUPS 注册表，
        删除覆盖即恢复默认成员）。"""
        group = self.get_group(group_id)
        is_fixed = bool(group.get("fixed"))
        member_id = (member_id or "").strip()
        if member_id in group["members"]:
            raise HTTPException(
                status_code=400,
                detail=f"该角色已在群中（不可重复添加）",
            )
        if len(group["members"]) >= MEMBERS_MAX:
            raise HTTPException(
                status_code=400, detail=f"群成员已达上限（{MEMBERS_MAX} 人）"
            )
        self._validate_member(member_id)
        cfg = character_service.get(member_id)
        group["members"].append(member_id)
        if is_fixed:
            self._fixed_overrides[group_id] = {
                "id": group_id,
                "name": group["name"],
                "members": group["members"],
                "created_at": group.get("created_at")
                or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "fixed": True,
            }
        self._save()
        return {"status": "success", "group_id": group_id,
                "name": cfg.name, "member_id": member_id,
                "members": group["members"]}

    def remove_member(self, group_id: str, member_id: str) -> dict:
        """移除群成员（动态群或固定群）：只从本群成员列表移除（该角色不再
        参与后续回复），不动历史/角色目录/配置/头像/启停状态。

        最后一名成员保护（第 68 条）：群内至少保留一名成员，最后一名
        不可移除（空群无意义——不能聊天还占列表）。
        固定群写入覆盖条目（删除覆盖即恢复 FIXED_GROUPS 默认成员）。"""
        group = self.get_group(group_id)
        is_fixed = bool(group.get("fixed"))
        member_id = (member_id or "").strip()
        if member_id not in group["members"]:
            raise HTTPException(
                status_code=400, detail=f"该角色不在群中: {member_id}"
            )
        if len(group["members"]) <= 1:
            raise HTTPException(
                status_code=400,
                detail="群内至少保留一名成员（最后一名不可移除）",
            )
        try:
            cfg = character_service.get(member_id)
            member_name = cfg.name
        except HTTPException:
            # 成员角色可能已被删除：仍允许从群里移除残留 ID
            member_name = member_id
        group["members"].remove(member_id)
        if is_fixed:
            self._fixed_overrides[group_id] = {
                "id": group_id,
                "name": group["name"],
                "members": group["members"],
                "created_at": group.get("created_at")
                or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "fixed": True,
            }
        self._save()
        return {"status": "success", "group_id": group_id,
                "name": member_name, "member_id": member_id,
                "members": group["members"]}

    # ==================== 改名 / 删除（第六阶段，第 69 条） ====================

    def rename_group(self, group_id: str, name: str) -> dict:
        """修改群名称（仅动态群，第 69 条）：固定群拒绝（400，名称是注册表
        常量）；不存在的群 404。名称去首尾空白、拒绝空/纯空白、上限
        GROUP_NAME_MAX（与创建一致，超长 400）。

        只改本群 name 字段：群 ID 不变（名称只做显示，绝不参与 ID/路径
        生成）、成员列表与其他群不受影响；_save 失败时回滚内存旧名
        （内存与文件保持一致）。前端群聊历史按 group_id 存储，改名后
        原历史继续显示（无需任何迁移）。"""
        if group_id in FIXED_GROUPS:
            raise HTTPException(
                status_code=400, detail="固定群不支持改名（名称由系统定义）"
            )
        group = self._groups.get(group_id)
        if group is None:
            raise HTTPException(status_code=404, detail=f"群聊不存在: {group_id}")
        name = (name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="群聊名称不能为空")
        if len(name) > GROUP_NAME_MAX:
            raise HTTPException(
                status_code=400, detail=f"群聊名称过长（最多 {GROUP_NAME_MAX} 字）"
            )
        old_name = group["name"]
        if name == old_name:
            return {"status": "success", "group_id": group_id, "name": name,
                    "members": list(group["members"])}
        group["name"] = name
        try:
            self._save()
        except HTTPException:
            group["name"] = old_name  # 回滚：文件写失败时内存保持原配置
            raise
        return {"status": "success", "group_id": group_id, "name": name,
                "members": list(group["members"])}

    def delete_group(self, group_id: str) -> dict:
        """删除群聊（仅动态群，第 69 条）：固定群拒绝（400）；不存在的群
        404（幂等语义明确——删除成功后再次删除同一 ID 返回 404，与既有
        add/remove 的「群不存在 404」约定一致）。

        只从 groups.json 移除该群条目（并防御性清理同 ID 覆盖条目——正常
        不会存在，固定群删除已被拒绝）：不动角色目录/character.json/头像/
        立绘/背景/TTS/角色启停，也不动其他群；群名称绝不拼接文件路径
        （删除按 ID 查内存字典）。_save 失败时恢复内存条目（内存与文件
        保持一致）。前端群聊历史（session 内）由前端自行清理。"""
        if group_id in FIXED_GROUPS:
            raise HTTPException(
                status_code=400, detail="固定群不支持删除"
            )
        group = self._groups.pop(group_id, None)
        if group is None:
            raise HTTPException(status_code=404, detail=f"群聊不存在: {group_id}")
        override = self._fixed_overrides.pop(group_id, None)
        try:
            self._save()
        except HTTPException:
            self._groups[group_id] = group  # 回滚：文件写失败时恢复原配置
            if override:
                self._fixed_overrides[group_id] = override
            raise
        return {"status": "success", "group_id": group_id,
                "name": group["name"]}



group_service = GroupService()