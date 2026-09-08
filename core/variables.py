"""变量替换引擎。

把文本中的 ``{{key}}`` 替换为上下文中的值；未知变量保留原样（不替换、不报错）。
上下文由调用方注入（persona / user_name / bot_name / time / date / datetime /
native_system / memories 以及 _conf_schema.json ``variables`` 中的自定义变量）。
"""

from __future__ import annotations

import json
import re

# 任务书规定：正则 {{(\w+)}} 匹配，查 dict 替换，找不到保留原样。
_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")

LIVING_MEMORY_TOOL_ID_PREFIX = "recall_long_term_memory"
"""LivingMemory 伪工具调用消息的 tool_call_id 前缀（任务书 M3 约定）。"""

_MEMORY_DICT_KEYS = ("memory", "text", "content", "fact")
"""记忆条目为对象时的常用文本字段兜底。"""


class VariableResolver:
    """``{{key}}`` 变量替换器。

    Args:
        context: 变量名 -> 值。值为 None 时按空字符串替换。
    """

    def __init__(self, context: dict | None = None):
        self._context: dict = dict(context or {})

    @property
    def context(self) -> dict:
        return dict(self._context)

    def update_context(self, context: dict) -> None:
        """合并注入新的变量（后者覆盖前者）。"""
        self._context.update(context or {})

    def resolve(self, text: str) -> str:
        """替换 text 中所有已知变量，返回替换后的文本。"""
        if not text:
            return text or ""

        def _replace(match: re.Match) -> str:
            key = match.group(1)
            if key not in self._context:
                return match.group(0)  # 未知变量保留原样
            value = self._context[key]
            return "" if value is None else str(value)

        return _VAR_PATTERN.sub(_replace, text)


def extract_memories(contexts) -> str:
    """从 req.contexts 中提取 LivingMemory 注入的记忆文本（``{{memories}}`` 取值）。

    识别规则（任务书 M3）：``role == "tool"`` 且 ``tool_call_id`` 以
    ``recall_long_term_memory`` 开头的消息。content 为 JSON 数组时取各元素
    文本后拼接，否则按原文；多条消息按出现顺序以换行拼接。

    只识别消息格式，不 import LivingMemory（AGPL 隔离）；提取不到返回空串。
    """
    parts: list[str] = []
    for msg in contexts or []:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        tool_call_id = str(msg.get("tool_call_id") or "")
        if not tool_call_id.startswith(LIVING_MEMORY_TOOL_ID_PREFIX):
            continue
        parts.extend(_memory_texts(msg.get("content")))
    return "\n".join(p for p in parts if p)


def _memory_texts(content) -> list[str]:
    """把单条 tool 消息的 content 归一化为记忆文本列表。"""
    if content is None:
        return []
    if isinstance(content, list):
        items = content
    else:
        text = str(content).strip()
        try:
            parsed = json.loads(text)
        except ValueError:
            return [text] if text else []
        items = parsed if isinstance(parsed, list) else [parsed]

    texts: list[str] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = ""
            for key in _MEMORY_DICT_KEYS:
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    break
            if not text:
                text = json.dumps(item, ensure_ascii=False)
        else:
            text = str(item)
        if text:
            texts.append(text)
    return texts
