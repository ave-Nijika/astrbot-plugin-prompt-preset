"""M4 预置条目测试：一次性预置、删除拦截、允许操作、保留前缀、空值跳过、预览占位。"""

import asyncio
import json

import pytest

from astrbot_plugin_prompt_preset.core.entry_store import (
    DEFAULT_PRESET_ENTRIES,
    PRESET_DELETE_MESSAGE,
    EntryStore,
    EntryValidationError,
)
from tests.helpers import make_plugin, make_store, run_command


def run(coro):
    return asyncio.run(coro)


def preset_names(store):
    return [e["name"] for e in store.list_entries() if e.get("preset")]


class TestPresetSeeding:
    def test_fresh_install_seeds_13_presets(self, tmp_path):
        store = EntryStore(tmp_path / "presets.json")
        assert len(store.list_entries()) == len(DEFAULT_PRESET_ENTRIES)
        assert len(preset_names(store)) == 13
        assert (tmp_path / "initialized.flag").exists()

    def test_preset_entries_persist_with_preset_flag(self, tmp_path):
        EntryStore(tmp_path / "presets.json")
        raw = json.loads((tmp_path / "presets.json").read_text(encoding="utf-8"))
        assert all(e["preset"] is True for e in raw)
        assert {e["id"] for e in raw} == {d["id"] for d in DEFAULT_PRESET_ENTRIES}

    def test_preset_orders_follow_verified_native_sequence(self, tmp_path):
        store = EntryStore(tmp_path / "presets.json")
        orders = {
            e["name"]: e["order"]
            for e in store.list_entries()
            if e.get("preset") and e["source"] == "text"
        }
        # 源码核实的真实执行顺序（见 m4_report §2）：safety 前置最前，websearch 最后
        assert orders["原生-安全模式"] == 100.0
        assert orders["原生-人格说明"] == 120.0
        assert orders["原生-技能说明"] == 140.0
        assert orders["原生-沙箱说明"] == 160.0
        assert orders["原生-工具说明"] == 180.0
        assert orders["原生-搜索引用"] == 200.0
        assert orders["原生-其他插件注入"] == 900.0
        history = store.get("preset-chat-history")
        assert history["source"] == "chat_history" and history["order"] == 1000.0

    def test_old_user_gets_presets_appended_without_touching_existing(self, tmp_path):
        """老用户（有旧条目但无标记）：预置追加到尾部，已有条目原样保留。"""
        path = tmp_path / "presets.json"
        path.write_text(
            json.dumps(
                [
                    {"order": 0, "name": "我的旧条目", "content": "自定义内容"},
                    {"order": 5, "name": "我的旧配置", "content": "x", "enabled": False},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        assert not (tmp_path / "initialized.flag").exists()  # 老用户无标记
        store = EntryStore(path)
        entries = store.list_entries()
        # 已有条目原样在前，预置追加在后
        assert entries[0]["name"] == "我的旧条目"
        assert entries[0]["content"] == "自定义内容"
        assert entries[1]["name"] == "我的旧配置"
        assert entries[1]["enabled"] is False
        assert len([e for e in entries if e.get("preset")]) == 13
        assert (tmp_path / "initialized.flag").exists()

    def test_flag_present_never_reseeds(self, tmp_path):
        """标记存在后，即使手改 presets.json 删掉预置条目也不再重建。"""
        path = tmp_path / "presets.json"
        EntryStore(path)  # 首次初始化：预置 + 打标记
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw = [e for e in raw if not e.get("preset")]  # 模拟手改文件删除预置条目
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        store = EntryStore(path)  # 重新加载
        assert preset_names(store) == []  # 不重建

    def test_flag_recreated_when_deleted_but_still_no_duplicate(self, tmp_path):
        """标记被手删：会补一次预置，但按固定 id 去重，不产生重复。"""
        path = tmp_path / "presets.json"
        EntryStore(path)
        (tmp_path / "initialized.flag").unlink()
        store = EntryStore(path)
        assert len(preset_names(store)) == 13  # 固定 id 去重，仍恰好 13 条

    def test_legacy_empty_scaffold_logs_hint(self, tmp_path, caplog):
        """旧版遗留空 text 条目：预置时输出 INFO 提示，但不自动删除。"""
        import logging

        path = tmp_path / "presets.json"
        path.write_text(
            json.dumps(
                [{"order": 10, "role": "system", "source": "text", "content": "", "name": "自定义提示词"}],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with caplog.at_level(logging.INFO):  # 捕获所有冒泡记录（logger 可能被 main 注入为 astrbot 全局 logger）
            EntryStore(path)
        assert any("检测到旧版空条目" in r.message for r in caplog.records)
        assert store_has_name(path, "自定义提示词")  # 未自动删除

    def test_no_hint_without_empty_scaffold(self, tmp_path, caplog):
        import logging

        path = tmp_path / "presets.json"
        path.write_text(
            json.dumps(
                [{"order": 1, "source": "text", "content": "有内容", "name": "实条目"}],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with caplog.at_level(logging.INFO):  # 捕获所有冒泡记录（logger 可能被 main 注入为 astrbot 全局 logger）
            EntryStore(path)
        assert not any("检测到旧版空条目" in r.message for r in caplog.records)


def store_has_name(path, name):
    return any(e["name"] == name for e in json.loads(path.read_text(encoding="utf-8")))


class TestDeleteInterception:
    def test_store_remove_preset_rejected(self, tmp_path):
        store = make_store(tmp_path, with_presets=True)
        with pytest.raises(EntryValidationError) as ei:
            store.remove("preset-native_safety")
        assert str(ei.value) == PRESET_DELETE_MESSAGE
        with pytest.raises(EntryValidationError, match="预置条目不可删除"):
            store.remove("原生-安全模式")  # 按名称同样拦截

    def test_store_remove_non_preset_ok(self, tmp_path):
        store = make_store(tmp_path, [{"order": 1, "name": "普通条目", "content": "x"}])
        assert store.remove("普通条目")["name"] == "普通条目"

    def test_api_delete_preset_returns_400_with_message(self, tmp_path):
        plugin = make_plugin(tmp_path, with_presets=True)
        result = run(plugin._api_entry_delete("preset-native_safety"))
        assert result["status"] == "error"
        assert result["status_code"] == 400
        assert result["message"] == PRESET_DELETE_MESSAGE
        assert plugin.store.get("preset-native_safety") is not None  # 仍在

    def test_http_delete_preset_rejected(self, tmp_path):
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from tests.test_dashboard_api import ApiHarness, build_fastapi_app

        harness = ApiHarness(tmp_path)
        harness.store.add({"order": 1, "name": "假装预置", "content": "x", "preset": True})
        entry_id = harness.store.list_entries()[0]["id"]
        client = TestClient(build_fastapi_app(harness.api))
        resp = client.delete(f"/api/prompt_preset/entries/{entry_id}")
        assert resp.status_code == 400
        assert resp.json()["message"] == PRESET_DELETE_MESSAGE

    def test_command_del_preset_rejected(self, tmp_path):
        plugin = make_plugin(tmp_path, with_presets=True)
        out = run_command(plugin, "/preset del 原生-安全模式")
        assert "预置条目不可删除" in out
        assert plugin.store.get("原生-安全模式") is not None

    def test_preset_edit_toggle_reorder_allowed(self, tmp_path):
        store = make_store(tmp_path, with_presets=True)
        # 编辑 content
        updated = store.update("preset-native_safety", {"content": "{{native_safety}}\n附加要求"})
        assert "附加要求" in updated["content"]
        # 开关
        assert store.toggle("preset-native_safety", False)["enabled"] is False
        # 排序
        assert store.reorder("preset-native_safety", 55.0)["order"] == 55.0
        # 均已落盘
        raw = json.loads((tmp_path / "presets.json").read_text(encoding="utf-8"))
        target = next(e for e in raw if e["id"] == "preset-native_safety")
        assert target["enabled"] is False and target["order"] == 55.0


class TestReservedPrefix:
    def test_config_native_vars_ignored_with_warning(self, tmp_path, caplog):
        import logging

        plugin = make_plugin(
            tmp_path,
            config={"variables": {"native_safety": "伪造", "user_name": "主人"}},
        )
        with caplog.at_level(logging.WARNING, logger="astrbot"):
            ctx = plugin._build_var_context("")
        assert "native_safety" not in ctx  # 忽略
        assert ctx["user_name"] == "主人"
        assert any("保留前缀 native_" in r.message for r in caplog.records)

    def test_reserved_filter_does_not_touch_normal_vars(self, tmp_path):
        plugin = make_plugin(
            tmp_path,
            config={"variables": {"bot_name_native_like": "x", "user_name": "主人"}},
        )
        ctx = plugin._build_var_context("")
        assert ctx["bot_name_native_like"] == "x"  # 非 native_ 前缀不受影响


class TestEmptySkip:
    def test_empty_resolved_text_entry_produces_no_message(self, tmp_path):
        from astrbot_plugin_prompt_preset.core.assembler import PromptAssembler

        store = make_store(
            tmp_path,
            [
                {"order": 0, "name": "空条目", "content": "{{native_safety}}"},  # 上下文无值 → 空
                {"order": 1, "name": "实条目", "content": "真实内容"},
            ],
        )
        asm = PromptAssembler(store)
        req = type("Req", (), {"system_prompt": "", "contexts": []})()
        run(asm.assemble(req, persona_text=""))
        assert req.system_prompt == "真实内容"  # 空条目未产生消息

    def test_whitespace_only_content_skipped(self, tmp_path):
        from astrbot_plugin_prompt_preset.core.assembler import PromptAssembler

        store = make_store(tmp_path, [{"order": 0, "name": "空白", "content": "  \n  "}])
        asm = PromptAssembler(store)
        req = type("Req", (), {"system_prompt": "原生", "contexts": []})()
        assert run(asm.assemble(req, persona_text="")) is False  # 全空 → 未接管
        assert req.system_prompt == "原生"  # 原生保持

    def test_persona_entry_not_affected_by_empty_skip(self, tmp_path):
        """persona 条目不受空值跳过影响（M1 语义保持：空 persona 也接管）。"""
        from astrbot_plugin_prompt_preset.core.assembler import PromptAssembler

        store = make_store(
            tmp_path,
            [{"order": 0, "name": "人格", "source": "persona", "content": ""}],
        )
        asm = PromptAssembler(store)
        req = type("Req", (), {"system_prompt": "原生", "contexts": []})()
        run(asm.assemble(req, persona_text=""))  # persona 为空
        assert req.system_prompt == ""  # persona 条目仍产生（空）消息 → 接管发生


class TestPreviewPlaceholders:
    def test_native_vars_show_placeholder_not_bare_braces(self, tmp_path):
        from astrbot_plugin_prompt_preset.core.assembler import PromptAssembler

        store = make_store(
            tmp_path,
            [{"order": 0, "name": "引用", "content": "{{native_system}} / {{native_safety}}"}],
        )
        asm = PromptAssembler(store)
        rows = asm.preview(persona_text="")
        snippet = rows[0]["snippet"]
        assert "{{" not in snippet  # 无裸占位符
        assert "（发消息时替换为 AstrBot 原生内容）" in snippet

    def test_real_value_wins_over_placeholder(self, tmp_path):
        """上下文里已有真实值（刚组装过）时保留真实值，占位仅兜底。"""
        from astrbot_plugin_prompt_preset.core.assembler import PromptAssembler

        store = make_store(tmp_path, [{"order": 0, "name": "引用", "content": "{{native_safety}}"}])
        asm = PromptAssembler(store)
        asm.set_context({"native_safety": "真实安全模式提示"})
        rows = asm.preview(persona_text="")
        assert rows[0]["snippet"] == "真实安全模式提示"

    def test_preset_list_via_command(self, tmp_path):
        plugin = make_plugin(tmp_path, with_presets=True)
        out = run_command(plugin, "/preset list")
        assert "13/13 启用" in out
        assert "原生-安全模式" in out and "对话历史" in out
