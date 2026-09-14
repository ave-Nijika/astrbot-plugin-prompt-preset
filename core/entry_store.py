"""条目持久化：JSON 文件存储。

存储位置：``data/plugin_data/astrbot_plugin_prompt_preset/presets.json``。
条目（Entry）数据模型见任务书：

    {"order": 0.0, "role": "system", "source": "text",
     "content": "...", "enabled": true, "name": "..."}

store 额外为每个条目生成一个管理用短 ``id``（不参与组装），使
``remove/update`` 等操作可以通过 id 精确定位同名条目。

本模块不依赖 astrbot，便于独立测试。
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import math
import os
import threading
import uuid
import logging
from pathlib import Path

logger = logging.getLogger("astrbot.plugin.prompt_preset")

VALID_ROLES = ("system", "user", "assistant")
VALID_SOURCES = ("text", "persona", "chat_history")

PRESET_FLAG_FILENAME = "initialized.flag"
"""预置一次性标记文件名（与 presets.json 同目录），内容为写入时间戳。"""

PRESET_DELETE_MESSAGE = "预置条目不可删除，如不需要请禁用该条目"

NATIVE_BLOCK_ORDERS = {
    # AstrBot v4.28 内置块真实执行顺序（core/splitter.py 注册表注释含源码出处）：
    # safety 最后前置到最前，websearch 引用提示最后注入。
    "native_safety": 100.0,
    "native_genui": 110.0,
    "native_persona": 120.0,
    "native_default_persona": 130.0,
    "native_skills": 140.0,
    "native_router": 150.0,
    "native_sandbox": 160.0,
    "native_local_mode": 170.0,
    "native_tools": 180.0,
    "native_live": 190.0,
    "native_websearch": 200.0,
}

DEFAULT_PRESET_ENTRIES: list[dict] = [
    {
        "id": f"preset-{name}",
        "order": order,
        "role": "system",
        "source": "text",
        "content": "{{" + name + "}}",
        "enabled": True,
        "name": f"原生-{label}",
        "preset": True,
    }
    for name, order, label in (
        ("native_safety", 100.0, "安全模式"),
        ("native_genui", 110.0, "ChatUI生成"),
        ("native_persona", 120.0, "人格说明"),
        ("native_default_persona", 130.0, "默认人格"),
        ("native_skills", 140.0, "技能说明"),
        ("native_router", 150.0, "路由提示"),
        ("native_sandbox", 160.0, "沙箱说明"),
        ("native_local_mode", 170.0, "本地模式"),
        ("native_tools", 180.0, "工具说明"),
        ("native_live", 190.0, "Live模式"),
        ("native_websearch", 200.0, "搜索引用"),
    )
] + [
    {
        "id": "preset-native-other",
        "order": 900.0,
        "role": "system",
        "source": "text",
        "content": "{{native_other}}",
        "enabled": True,
        "name": "原生-其他插件注入",
        "preset": True,
    },
    {
        # 对话历史：source=chat_history 展开原始 contexts（role 由消息自带）。
        "id": "preset-chat-history",
        "order": 1000.0,
        "role": "system",
        "source": "chat_history",
        "content": "",
        "enabled": True,
        "name": "对话历史",
        "preset": True,
    },
]


class EntryValidationError(ValueError):
    """条目数据不合法。"""


class EntryStore:
    """条目的内存缓存 + JSON 落盘。

    所有写操作即时保存；读取走内存缓存（热生效由调用方每次组装时
    重新 ``list_entries()`` 保证）。
    """

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self._entries: list[dict] = []
        self._lock = threading.RLock()
        self.load()
        self._ensure_presets()

    def _ensure_presets(self) -> None:
        """预置默认条目集（M4，一次性）。

        触发条件只看初始化标记（``initialized.flag``），不看条目列表——已有
        旧条目的老用户升级后同样追加预置，拿到原生块保护。预置动作：把默认
        模板条目**追加**到现有列表尾部（不删除、不修改任何已有条目），保存后
        写入标记；标记存在则永不再次预置。预置条目带固定 id，标记写入前若
        发生中断，下次启动按 id 去重，不会重复追加。
        """
        flag_path = self.path.parent / PRESET_FLAG_FILENAME
        with self._lock:
            if flag_path.exists():
                return
            existing_ids = {e.get("id") for e in self._entries}
            to_add = [e for e in DEFAULT_PRESET_ENTRIES if e["id"] not in existing_ids]
            if to_add:
                has_empty_scaffold = any(
                    e.get("source") == "text" and not (e.get("content") or "").strip()
                    for e in self._entries
                )
                for entry in to_add:
                    self._entries.append(_coerce_entry(entry))
                self.save()
                logger.info(
                    "[prompt_preset] 已预置 %d 条默认条目（原生内容保护），可在面板中禁用不需要的条目。",
                    len(to_add),
                )
                if has_empty_scaffold:
                    logger.info(
                        "[prompt_preset] 检测到旧版空条目，可能与预置条目重复，建议清理。"
                    )
            try:
                flag_path.parent.mkdir(parents=True, exist_ok=True)
                flag_path.write_text(
                    f"initialized at {_dt.datetime.now().isoformat(timespec='seconds')}\n",
                    encoding="utf-8",
                )
            except OSError as e:
                logger.error("[prompt_preset] 写入初始化标记失败（%s），下次启动可能重复预置", e)

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def load(self) -> list[dict]:
        """从 JSON 文件加载条目列表（覆盖内存状态）。

        文件不存在 → 空列表；文件损坏 → 备份为 ``<path>.bak`` 后从空开始。
        单条条目非法时跳过该条并告警，不影响其余条目。
        """
        with self._lock:
            if not self.path.exists():
                self._entries = []
                return self.list_entries()
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                backup = self.path.with_suffix(self.path.suffix + ".bak")
                try:
                    os.replace(self.path, backup)
                    logger.error(
                        "[prompt_preset] presets.json 解析失败(%s)，已备份为 %s，从空列表开始。", e, backup
                    )
                except OSError:
                    logger.error("[prompt_preset] presets.json 解析失败(%s)，且备份失败。", e)
                self._entries = []
                return self.list_entries()

            if isinstance(raw, dict):
                raw = raw.get("entries", [])  # 容忍 {"entries": [...]} 包装
            if not isinstance(raw, list):
                logger.error("[prompt_preset] presets.json 顶层不是数组，忽略文件内容。")
                self._entries = []
                return self.list_entries()

            entries: list[dict] = []
            for i, item in enumerate(raw):
                try:
                    entries.append(_coerce_entry(item))
                except EntryValidationError as e:
                    logger.warning("[prompt_preset] 跳过 presets.json 第 %d 条非法条目：%s", i + 1, e)
            self._entries = entries
            return self.list_entries()

    def reload(self) -> list[dict]:
        """重新从磁盘加载（/preset reload）。"""
        return self.load()

    def save(self) -> None:
        """原子写盘。"""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(self._entries, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp, self.path)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def list_entries(self) -> list[dict]:
        """所有条目的深拷贝，按 order 升序（同 order 保持插入顺序）。"""
        with self._lock:
            return copy.deepcopy(
                sorted(self._entries, key=lambda e: e.get("order", 0.0))
            )

    def enabled_entries(self) -> list[dict]:
        """enabled=true 的条目，按 order 升序。"""
        return [e for e in self.list_entries() if e.get("enabled", True)]

    def get(self, name_or_id: str) -> dict | None:
        """按 id（精确）或名称（首个匹配）查条目，返回深拷贝。"""
        with self._lock:
            found = self._find(name_or_id)
            return copy.deepcopy(found) if found else None

    def _find(self, name_or_id: str) -> dict | None:
        key = str(name_or_id)
        for entry in self._entries:
            if entry.get("id") == key:
                return entry
        for entry in self._entries:
            if entry.get("name") == key:
                return entry
        return None

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def add(self, entry: dict) -> dict:
        """新增条目（name 不可重复）。返回落库后的完整条目。"""
        coerced = _coerce_entry(entry)
        with self._lock:
            if any(e["name"] == coerced["name"] for e in self._entries):
                raise EntryValidationError(f"条目名已存在：{coerced['name']}")
            coerced["id"] = _new_id(self._entries)
            self._entries.append(coerced)
            self.save()
            return copy.deepcopy(coerced)

    def remove(self, name_or_id: str) -> dict | None:
        """删除条目，返回被删条目；不存在返回 None。

        M4：预置条目（preset=true）拒绝删除——预置把 AstrBot 原生内容交给
        用户排序/开关，删掉即失去原生保护；不需要时禁用即可。
        """
        with self._lock:
            found = self._find(name_or_id)
            if not found:
                return None
            if found.get("preset"):
                raise EntryValidationError(PRESET_DELETE_MESSAGE)
            self._entries.remove(found)
            self.save()
            return copy.deepcopy(found)

    def update(self, name_or_id: str, patch: dict) -> dict | None:
        """部分更新条目字段（id 不可改）。返回更新后的条目。"""
        with self._lock:
            found = self._find(name_or_id)
            if not found:
                return None
            merged = {**found, **(patch or {})}
            if "id" in patch:
                merged["id"] = found["id"]
            coerced = _coerce_entry(merged)
            new_name = coerced["name"]
            if new_name != found["name"] and any(e["name"] == new_name for e in self._entries):
                raise EntryValidationError(f"条目名已存在：{new_name}")
            self._entries[self._entries.index(found)] = coerced
            self.save()
            return copy.deepcopy(coerced)

    def reorder(self, name_or_id: str, new_order) -> dict | None:
        """修改条目排序权重。条目不存在返回 None。"""
        return self.update(name_or_id, {"order": new_order})

    def toggle(self, name_or_id: str, enabled: bool | None = None) -> dict | None:
        """启用/禁用条目；enabled=None 时翻转当前状态。"""
        with self._lock:
            found = self._find(name_or_id)
            if not found:
                return None
            if enabled is None:
                enabled = not bool(found.get("enabled", True))
            return self.update(name_or_id, {"enabled": bool(enabled)})


def _new_id(existing: list[dict]) -> str:
    taken = {e.get("id") for e in existing}
    while True:
        candidate = uuid.uuid4().hex[:8]
        if candidate not in taken:
            return candidate


def _coerce_entry(raw: dict) -> dict:
    """校验并规范化一个条目，非法时抛 EntryValidationError。"""
    if not isinstance(raw, dict):
        raise EntryValidationError(f"条目必须是对象，收到 {type(raw).__name__}")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise EntryValidationError("条目缺少有效的 name")
    name = name.strip()

    if "order" not in raw:
        raise EntryValidationError(f"条目「{name}」缺少 order")
    try:
        order = float(raw["order"])
    except (TypeError, ValueError):
        raise EntryValidationError(
            f"条目「{name}」的 order 必须是数字，收到 {raw['order']!r}"
        ) from None
    if not math.isfinite(order):
        raise EntryValidationError(f"条目「{name}」的 order 必须是有限数字")

    role = str(raw.get("role") or "system").strip().lower()
    if role not in VALID_ROLES:
        raise EntryValidationError(
            f"条目「{name}」的 role 必须是 {'/'.join(VALID_ROLES)}，收到 {raw.get('role')!r}"
        )

    source = str(raw.get("source") or "text").strip().lower()
    if source not in VALID_SOURCES:
        raise EntryValidationError(
            f"条目「{name}」的 source 必须是 {'/'.join(VALID_SOURCES)}，收到 {raw.get('source')!r}"
        )

    content = raw.get("content")
    content = "" if content is None else str(content)

    enabled = raw.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in ("1", "true", "yes", "on", "启用")
    enabled = bool(enabled)

    preset = raw.get("preset", False)
    if isinstance(preset, str):
        preset = preset.strip().lower() in ("1", "true", "yes", "on")
    preset = bool(preset)

    return {
        "order": order,
        "role": role,
        "source": source,
        "content": content,
        "enabled": enabled,
        "name": name,
        "preset": preset,
        "id": str(raw.get("id") or "").strip(),
    }
