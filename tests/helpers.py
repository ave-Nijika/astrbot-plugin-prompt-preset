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


class MockDashboardContext(MockContext):
    """带 register_web_api 的 context 替身：记录注册的面板路由。"""

    def __init__(self, persona=None, persona_error: Exception | None = None):
        super().__init__(persona, persona_error)
        self.registered_routes: list[tuple] = []

    def register_web_api(self, route, handler, methods, desc):
        self.registered_routes.append((route, handler, list(methods), desc))


class FakeApiRequest:
    """astrbot.api.web request 替身（monkeypatch main._api_request 用）。"""

    def __init__(self, method: str = "GET", payload=None):
        self.method = method
        self._payload = payload

    async def json(self, default=None):
        return self._payload if self._payload is not None else default


class MockProviderRequest:
    """ProviderRequest 替身：只暴露本插件读写的两个字段。"""

    def __init__(self, system_prompt: str = "", contexts=None):
        self.system_prompt = system_prompt
        self.contexts = list(contexts) if contexts is not None else []


def make_plugin(
    tmp_path,
    config: dict | None = None,
    persona=None,
    persona_error=None,
    context=None,
    with_presets=False,
):
    """构造挂在 tmp_path 存储上的插件实例（不触碰真实 data/ 目录）。"""
    from astrbot_plugin_prompt_preset.main import PromptPresetPlugin

    cfg = {"enable": True, "variables": {}}
    cfg.update(config or {})
    ctx = context if context is not None else MockContext(persona=persona, persona_error=persona_error)
    plugin = PromptPresetPlugin(ctx, config=cfg, store_path=tmp_path / "presets.json")
    if not with_presets:
        _strip_presets(plugin.store)
    return plugin


def normalize_prompt(text: str) -> str:
    """M4 等价性归一化（任务书规定）：按空行分段、逐段 strip、滤空后按序拼接。"""
    pieces = [p.strip() for p in (text or "").split("\n\n")]
    return "\n\n".join(p for p in pieces if p)


def _strip_presets(store) -> None:
    """剔除 store 中的预置条目并落盘（通用测试的空表语义，见 M4 with_presets）。"""
    store._entries = [e for e in store._entries if not e.get("preset")]
    store.save()


def make_store(tmp_path, entries=None, with_presets=False):
    """EntryStore 测试台架。

    M4 起新装初始化会自动预置 13 条「原生-*」条目；通用测试默认剔除
    （with_presets=False，保持既有测试语义），预置相关测试显式传 True。
    """
    from astrbot_plugin_prompt_preset.core.entry_store import EntryStore

    store = EntryStore(tmp_path / "presets.json")
    if not with_presets:
        _strip_presets(store)
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
