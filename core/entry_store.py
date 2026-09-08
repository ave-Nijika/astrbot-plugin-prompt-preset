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
        """删除条目，返回被删条目；不存在返回 None。"""
        with self._lock:
            found = self._find(name_or_id)
            if not found:
                return None
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

    return {
        "order": order,
        "role": role,
        "source": source,
        "content": content,
        "enabled": enabled,
        "name": name,
        "id": str(raw.get("id") or "").strip(),
    }
