"""astrbot_plugin_prompt_preset —— 提示词条目编排插件。

完全接管 AstrBot 的 LLM 请求组装：把 persona、对话历史、自定义文本全部变成
"条目"，每条有排序权重（order）和角色（role），插件按排序结果重建最终发给
LLM 的 messages 列表。条目列表为空或全部禁用时不做任何操作，保留 AstrBot
原生行为。
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register

try:  # AstrBot 以 data.plugins.<目录名>.main 作为包导入，相对导入可用
    from .core.assembler import PromptAssembler
    from .core.entry_store import EntryStore, EntryValidationError
except ImportError:  # 兜底：以普通目录方式加载时
    from core.assembler import PromptAssembler
    from core.entry_store import EntryStore, EntryValidationError

PLUGIN_NAME = "astrbot_plugin_prompt_preset"
PLUGIN_DATA_DIR = Path("data/plugin_data") / PLUGIN_NAME
PRESETS_FILE = PLUGIN_DATA_DIR / "presets.json"

VALID_ROLES = ("system", "user", "assistant")

USAGE = (
    "📖 提示词条目管理：\n"
    "/preset list —— 列出所有条目\n"
    "/preset show <name> —— 显示条目详情\n"
    "/preset add <order> <role> <name> <content> —— 添加条目（role: system/user/assistant）\n"
    "/preset del <name> —— 删除条目\n"
    "/preset move <name> <new_order> —— 修改排序\n"
    "/preset on <name> / off <name> —— 启用/禁用\n"
    "/preset reload —— 重新加载 presets.json\n"
    "/living_status —— 组装结果预览\n"
    "提示：persona/chat_history 类型条目与含空格内容请直接编辑 presets.json；条目名不能含空格。"
)


def parse_preset_message(message_str: str) -> tuple[str, str]:
    """把一条消息解析为 (子命令, 剩余文本)。

    兼容 ``preset ...`` 与 ``/preset ...`` 两种形态；空命令返回 ("help", "")。
    剩余文本保留原始空白（add 的 content 可能含空格）。
    """
    text = (message_str or "").strip()
    if text.startswith("/"):
        text = text.lstrip("/").strip()
    parts = text.split(None, 1)
    if parts and parts[0].lower() == "preset":
        text = parts[1].strip() if len(parts) > 1 else ""
    parts = text.split(None, 1)
    if not parts:
        return "help", ""
    return parts[0].lower(), parts[1].strip() if len(parts) > 1 else ""


@register(
    PLUGIN_NAME,
    "水煮冰糕",
    "提示词条目编排：完全接管 LLM 请求的消息组装，条目顺序/角色/开关完全由用户控制。",
    "v1.0.0",
)
class PromptPresetPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None, store_path=None):
        super().__init__(context)
        self.context = context
        # AstrBot v4 通过 context=..., config=... 实例化；config 为 AstrBotConfig（dict 子类）。
        self.config = config if isinstance(config, dict) else {}

        store_file = Path(store_path) if store_path else PRESETS_FILE
        self._presets_file_existed = store_file.exists()
        store_file.parent.mkdir(parents=True, exist_ok=True)
        self.store = EntryStore(store_file)
        self._seed_entries_from_config()
        self.assembler = PromptAssembler(self.store)
        logger.info(
            "[prompt_preset] 初始化完成：%d 条条目（%s）",
            len(self.store.list_entries()),
            store_file,
        )

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _seed_entries_from_config(self) -> None:
        """首次初始化（presets.json 尚不存在）时，把配置里的 entries 灌入存储。

        此后 presets.json 是唯一事实源；WebUI 修改 entries 不会回灌。
        """
        if self._presets_file_existed:
            return
        seed = self.config.get("entries") or []
        if not isinstance(seed, list):
            return
        for raw in seed:
            try:
                self.store.add(raw)
            except EntryValidationError as e:
                logger.warning("[prompt_preset] 跳过配置中的非法条目：%s", e)

    # ------------------------------------------------------------------
    # LLM 请求钩子（完全接管组装）
    # ------------------------------------------------------------------
    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """组装钩子：此时 req.system_prompt / req.contexts 已含 AstrBot 原生注入。"""
        if not self._enabled():
            return
        try:
            entries = self.store.list_entries()
            if not any(e.get("enabled", True) for e in entries):
                return  # 空列表 / 全禁用：保留 AstrBot 原生行为
            persona_text = await self._get_persona_text(event)
            self.assembler.set_context(self._build_var_context(persona_text))
            await self.assembler.assemble(req, persona_text)
        except Exception as e:  # 组装出错时不阻断请求，回退原生组装
            logger.error(f"[prompt_preset] 组装失败，本次请求保留 AstrBot 原生组装：{e}")
            logger.exception("assemble failed")

    def _enabled(self) -> bool:
        # 每次动态读取，配合 WebUI 修改配置即时生效。
        return bool(self.config.get("enable", True))

    async def _get_persona_text(self, event: AstrMessageEvent) -> str:
        """当前 persona 全文（v4 的 Personality.prompt 字段）。"""
        try:
            persona_manager = getattr(self.context, "persona_manager", None)
            if persona_manager is None:
                return ""
            umo = getattr(event, "unified_msg_origin", None)
            persona = await persona_manager.get_default_persona_v3(umo)
        except Exception as e:
            logger.warning(f"[prompt_preset] 获取 persona 失败：{e}")
            return ""
        return _extract_persona_prompt(persona)

    def _build_var_context(self, persona_text: str) -> dict:
        now = _dt.datetime.now()
        ctx = dict(self.config.get("variables") or {})
        ctx.update(
            {
                "persona": persona_text,
                "time": now.strftime("%H:%M"),
                "date": now.strftime("%Y-%m-%d"),
                "datetime": now.strftime("%Y-%m-%d %H:%M"),
            }
        )
        return ctx

    # ------------------------------------------------------------------
    # /preset 命令
    # ------------------------------------------------------------------
    @filter.command("preset")
    async def preset(self, event: AstrMessageEvent):
        """提示词条目管理：list/show/add/del/move/on/off/reload/status。"""
        sub, rest = parse_preset_message(event.message_str)
        if sub == "list":
            yield event.plain_result(self._cmd_list())
        elif sub == "show":
            yield event.plain_result(self._cmd_show(rest))
        elif sub == "add":
            yield event.plain_result(self._cmd_add(rest))
        elif sub == "del":
            yield event.plain_result(self._cmd_del(rest))
        elif sub == "move":
            yield event.plain_result(self._cmd_move(rest))
        elif sub == "on":
            yield event.plain_result(self._cmd_toggle(rest, True))
        elif sub == "off":
            yield event.plain_result(self._cmd_toggle(rest, False))
        elif sub == "reload":
            yield event.plain_result(self._cmd_reload())
        elif sub == "status":
            yield event.plain_result(await self._cmd_status(event))
        else:
            yield event.plain_result(USAGE)

    @filter.command("living_status")
    async def living_status(self, event: AstrMessageEvent):
        """显示当前组装结果预览（调试用）。"""
        yield event.plain_result(await self._cmd_status(event))

    # ------------------------------------------------------------------
    # 命令实现（返回纯文本）
    # ------------------------------------------------------------------
    def _cmd_list(self) -> str:
        entries = self.store.list_entries()
        if not entries:
            return "📭 暂无条目。用 /preset add <order> <role> <name> <content> 添加；当前保持 AstrBot 原生组装。"
        enabled_n = sum(1 for e in entries if e.get("enabled", True))
        lines = [f"📋 提示词条目（{enabled_n}/{len(entries)} 启用，按 order 升序）："]
        for i, e in enumerate(entries, 1):
            mark = "✅" if e.get("enabled", True) else "❌"
            lines.append(
                f"{i}. {mark} {e['name']}｜order={e['order']:g}｜{e['role']}｜{e['source']}"
            )
        return "\n".join(lines)

    def _cmd_show(self, name: str) -> str:
        if not name:
            return "用法：/preset show <name>"
        entry = self.store.get(name)
        if not entry:
            return f"未找到条目：{name}（用 /preset list 查看全部）"
        mark = "✅ 启用" if entry.get("enabled", True) else "❌ 禁用"
        content = entry.get("content", "")
        shown = content if len(content) <= 800 else content[:800] + f" …（共 {len(content)} 字）"
        return (
            f"📄 条目「{entry['name']}」（id:{entry.get('id', '-')}）\n"
            f"order: {entry['order']:g}\nrole: {entry['role']}\n"
            f"source: {entry['source']}\nenabled: {mark}\ncontent:\n{shown}"
        )

    def _cmd_add(self, rest: str) -> str:
        parts = rest.split(None, 3)
        if len(parts) < 3:
            return "用法：/preset add <order> <role> <name> <content>\n示例：/preset add 5 system 思考框架 回复前先思考"
        order_raw, role_raw, name = parts[0], parts[1].lower(), parts[2]
        content = parts[3] if len(parts) > 3 else ""
        if role_raw not in VALID_ROLES:
            return f"role 必须是 {'/'.join(VALID_ROLES)}，收到：{parts[1]}"
        try:
            entry = self.store.add(
                {
                    "order": order_raw,
                    "role": role_raw,
                    "name": name,
                    "content": content,
                    "source": "text",
                    "enabled": True,
                }
            )
        except EntryValidationError as e:
            return f"添加失败：{e}"
        return f"✅ 已添加条目「{entry['name']}」（order={entry['order']:g}，role={entry['role']}，source={entry['source']}）"

    def _cmd_del(self, name: str) -> str:
        if not name:
            return "用法：/preset del <name>"
        removed = self.store.remove(name)
        if not removed:
            return f"未找到条目：{name}"
        return f"🗑 已删除条目「{removed['name']}」（order={removed['order']:g}）"

    def _cmd_move(self, rest: str) -> str:
        parts = rest.split()
        if len(parts) != 2:
            return "用法：/preset move <name> <new_order>"
        name, order_raw = parts[0], parts[1]
        try:
            updated = self.store.reorder(name, order_raw)
        except EntryValidationError as e:
            return f"移动失败：{e}"
        if not updated:
            return f"未找到条目：{name}"
        return f"✅ 条目「{updated['name']}」order → {updated['order']:g}"

    def _cmd_toggle(self, name: str, enable: bool) -> str:
        if not name:
            return f"用法：/preset {'on' if enable else 'off'} <name>"
        updated = self.store.toggle(name, enable)
        if not updated:
            return f"未找到条目：{name}"
        state = "启用" if updated.get("enabled", True) else "禁用"
        return f"✅ 条目「{updated['name']}」已{state}"

    def _cmd_reload(self) -> str:
        entries = self.store.reload()
        return f"🔄 已重新加载 presets.json，共 {len(entries)} 条条目。"

    async def _cmd_status(self, event: AstrMessageEvent) -> str:
        persona_text = await self._get_persona_text(event)
        self.assembler.set_context(self._build_var_context(persona_text))
        rows = self.assembler.preview(chat_history=[], persona_text=persona_text, width=50)
        if not rows:
            return "📊 当前没有启用的条目：插件未接管组装，保持 AstrBot 原生行为。"
        lines = [
            f"📊 组装预览（{len(rows)} 条启用条目，按 order 升序；"
            "chat_history 条目实际请求时展开完整对话历史）："
        ]
        for i, row in enumerate(rows, 1):
            snippet = row["snippet"].replace("\n", " ")
            lines.append(
                f"{i}. [{row['role']}/{row['source']}] {row['name']}｜order={row['order']:g}"
                f"｜{row['length']}字：{snippet}"
            )
        return "\n".join(lines)


def _extract_persona_prompt(persona) -> str:
    """从 persona 对象/字典中取出人格全文（v4 字段为 prompt，兼容旧字段 system_prompt）。"""
    if not persona:
        return ""
    if isinstance(persona, dict):
        for key in ("prompt", "system_prompt"):
            value = persona.get(key)
            if isinstance(value, str) and value:
                return value
        return ""
    for attr in ("prompt", "system_prompt"):
        value = getattr(persona, attr, None)
        if isinstance(value, str) and value:
            return value
    return ""
