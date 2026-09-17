"""紧急修复（POST 分支失效）回归测试。

P0 根因：`_api_request` 在真实 AstrBot 环境为 None，旧 `_api_entries()`
用 `if _api_request and _api_request.method == "POST"` 区分添加/列表，
条件恒 False → POST 永远走 GET 分支返回列表，条目从不落盘。

修复：路由按 HTTP 方法绑定独立 handler（`_api_entries_get/_post` 等），
handler 不读取 `_api_request.method`；请求体经 `_request_json()` 获取，
其回退路径直接读 `astrbot.api.web.request`（VM 上可用）。

本文件在**模拟 VM 环境**（`_api_request = None`）下验证各 handler 行为，
并锚定路由注册表拆分与请求体回退链路。
"""

import asyncio
import json
import sys

import pytest

from tests.helpers import FakeApiRequest, make_plugin


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def vm_mode(monkeypatch):
    """把 main 模块打到真实环境状态：_api_request = None。"""
    import astrbot_plugin_prompt_preset.main as plugin_main

    monkeypatch.setattr(plugin_main, "_api_request", None)
    return plugin_main


def stub_web_request(monkeypatch, payload):
    """给 astrbot.api.web 桩模块换上带 payload 的 request（模拟 VM 回退路径）。"""
    import types

    import astrbot.api.web as web_module

    class _Req:
        method = "POST"

        async def json(self, default=None):
            return payload if payload is not None else default

    monkeypatch.setattr(web_module, "request", _Req(), raising=False)


class TestVmModePostPersists:
    def test_entries_post_persists_to_presets_json(self, tmp_path, vm_mode, monkeypatch):
        """P0 核心验证：VM 环境（_api_request=None）下 POST 落盘 presets.json。"""
        stub_web_request(monkeypatch, {"order": 1, "name": "思维协议A", "content": "协议内容"})
        plugin = make_plugin(tmp_path, with_presets=True)
        before = len(plugin.store.list_entries())

        result = run(plugin._api_entries_post())
        assert result["status"] == "ok"
        assert result["data"]["entry"]["name"] == "思维协议A"

        # 落盘确认：从磁盘重新加载（模拟插件重启后仍在）
        fresh = type(plugin.store)(plugin.store.path)
        names = [e["name"] for e in fresh.list_entries()]
        assert "思维协议A" in names
        assert len(fresh.list_entries()) == before + 1

    def test_entries_post_response_carries_entry_id(self, tmp_path, vm_mode, monkeypatch):
        """响应必须带完整 entry（含 id）——前端 Bug 4 的空值防护依赖它。"""
        stub_web_request(monkeypatch, {"order": 2, "name": "带ID检查"})
        plugin = make_plugin(tmp_path)
        result = run(plugin._api_entries_post())
        entry = result["data"]["entry"]
        assert entry["id"]  # 前端 state.selectedId = data.entry.id 不再得到 undefined
        assert plugin.store.get(entry["id"])["name"] == "带ID检查"

    def test_variables_put_persists_in_vm_mode(self, tmp_path, vm_mode, monkeypatch):
        """同一根因的 variables PUT/POST 别名分支：VM 环境下可写入配置。"""
        stub_web_request(monkeypatch, {"variables": {"user_name": "主人", "mood": "开心"}})
        plugin = make_plugin(tmp_path, config={"variables": {"user_name": "旧值"}})
        result = run(plugin._api_variables_put())
        assert result["status"] == "ok"
        assert result["data"]["variables"]["mood"] == "开心"
        assert plugin.config["variables"]["mood"] == "开心"  # setter 已执行

    def test_entries_get_works_in_vm_mode(self, tmp_path, vm_mode):
        plugin = make_plugin(tmp_path)
        plugin.store.add({"order": 0, "name": "已有条目", "content": "x"})
        result = run(plugin._api_entries_get())
        assert [e["name"] for e in result["data"]["entries"]] == ["已有条目"]

    def test_request_json_fallback_reads_web_module(self, tmp_path, vm_mode, monkeypatch):
        """_request_json 回退链：_api_request=None 时读 astrbot.api.web.request。"""
        stub_web_request(monkeypatch, {"k": "v"})
        result = run(plugin_main_request_json())
        assert result == {"k": "v"}


def plugin_main_request_json():
    import astrbot_plugin_prompt_preset.main as plugin_main

    return plugin_main._request_json(default=None)


class TestRegression:
    def test_fake_request_path_still_works(self, tmp_path, monkeypatch):
        """测试台架旧路径（FakeApiRequest 注入 _api_request）不受拆分影响。"""
        import astrbot_plugin_prompt_preset.main as plugin_main

        plugin = make_plugin(tmp_path)
        monkeypatch.setattr(
            plugin_main, "_api_request", FakeApiRequest("POST", {"order": 3, "name": "旧路径"})
        )
        result = run(plugin._api_entries_post())
        assert result["status"] == "ok"
        assert result["data"]["entry"]["name"] == "旧路径"

    def test_invalid_payload_still_converts_to_error(self, tmp_path, vm_mode, monkeypatch):
        stub_web_request(monkeypatch, {"order": 1, "role": "boss", "name": "x"})
        plugin = make_plugin(tmp_path)
        result = run(plugin._api_entries_post())
        assert result["status"] == "error"
        assert result["status_code"] == 400

    def test_entry_put_update_persists(self, tmp_path, vm_mode, monkeypatch):
        """PUT 更新路径（_request_json 直接读取，原本就可用）保持可用。"""
        plugin = make_plugin(tmp_path)
        plugin.store.add({"order": 1, "name": "旧内容", "content": "a"})
        entry_id = plugin.store.get("旧内容")["id"]
        stub_web_request(monkeypatch, {"content": "b"})
        result = run(plugin._api_entry_put(entry_id))
        assert result["status"] == "ok"
        fresh = type(plugin.store)(plugin.store.path)
        assert fresh.get("旧内容")["content"] == "b"
