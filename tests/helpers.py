"""测试公共工具：mock event / context / req，插件工厂，async 运行辅助。"""

from __future__ import annotations

import asyncio


class MockEvent:
    """最小化 AstrMessageEvent 替身。"""

    def __init__(self, message_str: str = "", unified_msg_origin: str = "moc-session"):
        self.message_str = message_str
        self.unified_msg_origin = unified_msg_origin

    def plain_result(self, text) -> str:
        return str(text)


class MockPersonaManager:
    def __init__(self, persona=None, error: Exception | None = None):
        self.persona = persona
        self.error = error
        self.calls: list = []

    async def get_default_persona_v3(self, umo=None):
        self.calls.append(umo)
        if self.error is not None:
            raise self.error
        return self.persona


class MockContext:
    def __init__(self, persona=None, persona_error: Exception | None = None):
        self.persona_manager = MockPersonaManager(persona, persona_error)


class MockProviderRequest:
    """ProviderRequest 替身：只暴露本插件读写的两个字段。"""

    def __init__(self, system_prompt: str = "", contexts=None):
        self.system_prompt = system_prompt
        self.contexts = list(contexts) if contexts is not None else []


def make_plugin(tmp_path, config: dict | None = None, persona=None, persona_error=None):
    """构造挂在 tmp_path 存储上的插件实例（不触碰真实 data/ 目录）。"""
    from astrbot_plugin_prompt_preset.main import PromptPresetPlugin

    cfg = {"enable": True, "variables": {}}
    cfg.update(config or {})
    return PromptPresetPlugin(
        MockContext(persona=persona, persona_error=persona_error),
        config=cfg,
        store_path=tmp_path / "presets.json",
    )


def make_store(tmp_path, entries=None):
    from astrbot_plugin_prompt_preset.core.entry_store import EntryStore

    store = EntryStore(tmp_path / "presets.json")
    for entry in entries or []:
        store.add(entry)
    return store


def run(coro):
    return asyncio.run(coro)


async def collect(agen) -> list:
    return [item async for item in agen]


def run_command(plugin, message_str: str, umo: str = "moc-session") -> str:
    """执行聊天命令（自动选择 /preset 或 /living_status handler）并拼接输出。"""
    event = MockEvent(message_str, umo)
    first_token = message_str.strip().lstrip("/").split(None, 1)[0]
    handler = plugin.living_status if first_token == "living_status" else plugin.preset
    outputs = run(collect(handler(event)))
    assert outputs, f"命令无输出：{message_str!r}"
    return "\n".join(outputs)


def run_hook(plugin, req, umo: str = "moc-session") -> None:
    run(plugin.on_llm_request(MockEvent("", umo), req))
