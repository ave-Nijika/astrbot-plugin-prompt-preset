"""组装引擎：条目排序 → 消息列表重建，完全接管 AstrBot 的消息组装。

接管语义（见任务书）：

1. 读取启用的条目，按 order 升序；
2. 逐条生成消息：
   - source=text        → content 做变量替换后按 role 生成消息；
   - source=persona     → persona 全文作为 content（role 按条目配置）；
   - source=chat_history→ 将 req.contexts 中的原始消息展开插入当前位置
     （保持原始顺序与 role，含 LivingMemory 注入的 fake messages）；
3. 所有 role=system 的消息按 order 顺序用空行拼接为 req.system_prompt；
   其余消息完全替换 req.contexts；
4. 条目列表为空或全部 disabled → 不做任何操作（保留 AstrBot 原生行为）。

本模块不依赖 astrbot，便于独立测试。
"""

from __future__ import annotations

from .entry_store import EntryStore
from .variables import VariableResolver

SYSTEM_JOIN = "\n\n"
"""多条 system 条目拼入 system_prompt 时的连接符。"""


class PromptAssembler:
    def __init__(self, store: EntryStore, context: dict | None = None):
        """context: 变量基础上下文（persona 除外），每次组装前由调用方刷新。"""
        self.store = store
        self._context: dict = dict(context or {})

    def set_context(self, context: dict) -> None:
        """刷新变量基础上下文（时间类变量每次请求都要重算）。"""
        self._context = dict(context or {})

    async def assemble(self, req, persona_text: str) -> bool:
        """完全接管消息组装，写回 req.system_prompt 与 req.contexts。

        Returns:
            bool: 是否发生了接管。False 表示未做任何操作
            （条目列表为空 / 全部禁用 / 重建结果为空），req 保持原样。
        """
        entries = self._enabled_entries()
        if not entries:
            return False
        chat_history = list(getattr(req, "contexts", None) or [])
        messages = self.build_messages(entries, chat_history, persona_text)
        if not messages:
            return False

        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        rest = [m for m in messages if m.get("role") != "system"]
        req.system_prompt = SYSTEM_JOIN.join(system_parts)
        req.contexts = rest
        return True

    def build_messages(
        self, entries: list[dict], chat_history: list[dict], persona_text: str
    ) -> list[dict]:
        """按 order 升序把条目展开为消息列表（不写回 req）。"""
        resolver = VariableResolver({**self._context, "persona": persona_text})
        messages: list[dict] = []
        for entry in sorted(entries, key=lambda e: float(e.get("order", 0.0))):
            source = entry.get("source", "text")
            role = entry.get("role", "system")
            if source == "text":
                messages.append(
                    {"role": role, "content": resolver.resolve(entry.get("content", ""))}
                )
            elif source == "persona":
                messages.append({"role": role, "content": persona_text or ""})
            elif source == "chat_history":
                # 原样展开：保持原始顺序、role 及全部字段（含工具调用等）。
                messages.extend(dict(m) for m in chat_history)
        return messages

    def preview(
        self,
        chat_history: list[dict] | None = None,
        persona_text: str = "",
        width: int = 50,
    ) -> list[dict]:
        """组装结果预览（/living_status 调试用），返回每条启用条目的一行摘要。"""
        history = list(chat_history or [])
        resolver = VariableResolver({**self._context, "persona": persona_text})
        rows: list[dict] = []
        for entry in self._enabled_entries():
            source = entry.get("source", "text")
            if source == "text":
                content = resolver.resolve(entry.get("content", ""))
                length, snippet = len(content), content[:width]
            elif source == "persona":
                content = persona_text or ""
                length, snippet = len(content), content[:width]
            else:  # chat_history
                length = len(history)
                snippet = f"<对话历史：实际请求时在此展开 {length} 条消息>"
            rows.append(
                {
                    "order": float(entry.get("order", 0.0)),
                    "role": entry.get("role", "system"),
                    "source": source,
                    "name": entry.get("name", ""),
                    "length": length,
                    "snippet": snippet,
                }
            )
        return rows

    def _enabled_entries(self) -> list[dict]:
        return [e for e in self.store.list_entries() if e.get("enabled", True)]
