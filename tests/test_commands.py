"""聊天命令测试：mock event 验证参数解析与各命令的调用。"""

import json

from astrbot_plugin_prompt_preset.core.entry_store import EntryStore
from astrbot_plugin_prompt_preset.main import USAGE, parse_preset_message
from tests.helpers import make_plugin, run_command, run_hook

PERSONA = {"prompt": "你是凛，主人的AI伴侣。", "name": "凛"}


class TestParser:
    def test_plain(self):
        assert parse_preset_message("preset list") == ("list", "")

    def test_with_slash(self):
        assert parse_preset_message("/preset list") == ("list", "")

    def test_add_with_content(self):
        assert parse_preset_message("/preset add 1 system 框架 先思考 再回复") == (
            "add",
            "1 system 框架 先思考 再回复",
        )

    def test_bare_command(self):
        assert parse_preset_message("preset") == ("help", "")

    def test_empty(self):
        assert parse_preset_message("") == ("help", "")
        assert parse_preset_message("/preset") == ("help", "")

    def test_slash_only_prefix(self):
        assert parse_preset_message("/preset") == ("help", "")

    def test_case_insensitive_subcommand(self):
        assert parse_preset_message("preset LIST")[0] == "list"

    def test_rest_preserved(self):
        assert parse_preset_message("preset move 名称 2.5") == ("move", "名称 2.5")


class TestAddCommand:
    def test_add_basic(self, tmp_path):
        plugin = make_plugin(tmp_path)
        out = run_command(plugin, "/preset add 5 system 思考框架 回复前先思考再回答")
        assert "已添加" in out
        entry = plugin.store.get("思考框架")
        assert entry["order"] == 5.0
        assert entry["role"] == "system"
        assert entry["content"] == "回复前先思考再回答"
        assert entry["source"] == "text"
        assert entry["enabled"] is True

    def test_add_content_with_spaces(self, tmp_path):
        plugin = make_plugin(tmp_path)
        run_command(plugin, "/preset add 0 assistant 独白 我 想 一 想")
        assert plugin.store.get("独白")["content"] == "我 想 一 想"

    def test_add_empty_content(self, tmp_path):
        plugin = make_plugin(tmp_path)
        run_command(plugin, "/preset add 1 user 占位")
        assert plugin.store.get("占位")["content"] == ""

    def test_add_missing_args(self, tmp_path):
        plugin = make_plugin(tmp_path)
        out = run_command(plugin, "/preset add 1 system")
        assert "用法" in out
        assert plugin.store.list_entries() == []

    def test_add_invalid_role(self, tmp_path):
        plugin = make_plugin(tmp_path)
        out = run_command(plugin, "/preset add 1 boss 老板 内容")
        assert "role" in out
        assert plugin.store.list_entries() == []

    def test_add_invalid_order(self, tmp_path):
        plugin = make_plugin(tmp_path)
        out = run_command(plugin, "/preset add abc system 名 内容")
        assert "添加失败" in out
        assert plugin.store.list_entries() == []

    def test_add_duplicate_name(self, tmp_path):
        plugin = make_plugin(tmp_path)
        run_command(plugin, "/preset add 1 system 名 内容")
        out = run_command(plugin, "/preset add 2 user 名 内容2")
        assert "已存在" in out
        assert len(plugin.store.list_entries()) == 1


class TestListShowDel:
    def test_list_empty(self, tmp_path):
        plugin = make_plugin(tmp_path)
        out = run_command(plugin, "preset list")
        assert "暂无条目" in out

    def test_list_sorted_with_marks(self, tmp_path):
        plugin = make_plugin(tmp_path)
        plugin.store.add({"order": 10, "name": "后", "content": "b"})
        plugin.store.add({"order": 0, "name": "先", "role": "user", "content": "a"})
        plugin.store.add({"order": 5, "name": "关", "content": "c", "enabled": False})
        out = run_command(plugin, "/preset list")
        lines = out.splitlines()
        assert "2/3 启用" in lines[0]
        names = [line for line in lines if "｜" in line]
        assert names[0].startswith("1.") and "先" in names[0] and "✅" in names[0]
        assert "user" in names[0]
        assert "关" in names[1] and "❌" in names[1]

    def test_show_existing(self, tmp_path):
        plugin = make_plugin(tmp_path)
        plugin.store.add({"order": 2.5, "role": "assistant", "name": "独白", "content": "想一想"})
        out = run_command(plugin, "/preset show 独白")
        assert "独白" in out and "2.5" in out and "assistant" in out and "想一想" in out

    def test_show_missing(self, tmp_path):
        plugin = make_plugin(tmp_path)
        out = run_command(plugin, "/preset show 不存在")
        assert "未找到" in out

    def test_show_no_arg(self, tmp_path):
        plugin = make_plugin(tmp_path)
        assert "用法" in run_command(plugin, "/preset show")

    def test_del_existing(self, tmp_path):
        plugin = make_plugin(tmp_path)
        plugin.store.add({"order": 1, "name": "旧", "content": "x"})
        out = run_command(plugin, "/preset del 旧")
        assert "已删除" in out
        assert plugin.store.list_entries() == []

    def test_del_missing(self, tmp_path):
        plugin = make_plugin(tmp_path)
        assert "未找到" in run_command(plugin, "/preset del 不存在")


class TestMoveToggleReload:
    def test_move(self, tmp_path):
        plugin = make_plugin(tmp_path)
        plugin.store.add({"order": 1, "name": "条目", "content": "x"})
        out = run_command(plugin, "/preset move 条目 7.5")
        assert "7.5" in out
        assert plugin.store.get("条目")["order"] == 7.5

    def test_move_bad_order(self, tmp_path):
        plugin = make_plugin(tmp_path)
        plugin.store.add({"order": 1, "name": "条目", "content": "x"})
        out = run_command(plugin, "/preset move 条目 快")
        assert "移动失败" in out
        assert plugin.store.get("条目")["order"] == 1.0

    def test_move_missing(self, tmp_path):
        plugin = make_plugin(tmp_path)
        assert "未找到" in run_command(plugin, "/preset move 不存在 1")

    def test_on_off(self, tmp_path):
        plugin = make_plugin(tmp_path)
        plugin.store.add({"order": 1, "name": "开关", "content": "x"})
        assert "已禁用" in run_command(plugin, "/preset off 开关")
        assert plugin.store.get("开关")["enabled"] is False
        assert "已启用" in run_command(plugin, "/preset on 开关")
        assert plugin.store.get("开关")["enabled"] is True

    def test_toggle_persisted(self, tmp_path):
        plugin = make_plugin(tmp_path)
        plugin.store.add({"order": 1, "name": "开关", "content": "x"})
        run_command(plugin, "/preset off 开关")
        assert EntryStore(tmp_path / "presets.json").get("开关")["enabled"] is False

    def test_reload_picks_up_external_edit(self, tmp_path):
        plugin = make_plugin(tmp_path)
        plugin.store.add({"order": 1, "name": "旧条目", "content": "x"})
        # 模拟外部直接编辑 presets.json
        path = tmp_path / "presets.json"
        path.write_text(
            json.dumps([{"order": 3, "name": "外部条目", "content": "手改"}], ensure_ascii=False),
            encoding="utf-8",
        )
        out = run_command(plugin, "/preset reload")
        assert "重新加载" in out and "1" in out
        assert plugin.store.get("旧条目") is None
        assert plugin.store.get("外部条目")["order"] == 3.0


class TestStatusAndHelp:
    def test_living_status_with_entries(self, tmp_path):
        plugin = make_plugin(tmp_path, persona=PERSONA)
        plugin.store.add({"order": 0, "role": "system", "name": "人格", "source": "persona"})
        plugin.store.add({"order": 2, "role": "user", "name": "历史", "source": "chat_history"})
        plugin.store.add({"order": 1, "role": "system", "name": "长文本", "content": "字" * 80})
        out = run_command(plugin, "/living_status")
        assert "3 条启用条目" in out
        assert "人格" in out and "凛" in out
        assert "长文本" in out and "字" * 50 in out and "字" * 51 not in out  # 截断到 50 字
        lines = [line for line in out.splitlines() if line[0].isdigit()]
        assert lines[0].split()[1] == "[system/persona]"  # order=0 的人格在前
        assert lines[1].split()[1] == "[system/text]"  # order=1 的长文本居中
        assert any("chat_history" in line for line in lines)  # order=2 的历史在后

    def test_living_status_empty(self, tmp_path):
        plugin = make_plugin(tmp_path)
        out = run_command(plugin, "/living_status")
        assert "没有启用" in out

    def test_status_alias(self, tmp_path):
        plugin = make_plugin(tmp_path)
        assert "没有启用" in run_command(plugin, "/preset status")

    def test_unknown_subcommand_shows_usage(self, tmp_path):
        plugin = make_plugin(tmp_path)
        assert run_command(plugin, "/preset 不存在的命令") == USAGE

    def test_bare_preset_shows_usage(self, tmp_path):
        plugin = make_plugin(tmp_path)
        assert run_command(plugin, "/preset") == USAGE


class TestHookGuards:
    def test_enable_false_keeps_native(self, tmp_path):
        plugin = make_plugin(tmp_path, config={"enable": False})
        plugin.store.add({"order": 0, "name": "条目", "content": "x"})
        req = type("Req", (), {"system_prompt": "原生", "contexts": []})()
        run_hook(plugin, req)
        assert req.system_prompt == "原生"

    def test_persona_manager_error_still_assembles(self, tmp_path):
        plugin = make_plugin(tmp_path, persona_error=RuntimeError("db down"))
        plugin.store.add({"order": 0, "role": "system", "name": "人格", "source": "persona"})
        plugin.store.add({"order": 1, "role": "system", "name": "文本", "content": "hi"})
        req = type("Req", (), {"system_prompt": "原生", "contexts": []})()
        run_hook(plugin, req)
        assert req.system_prompt == "\n\nhi"  # persona 拿不到 → 空串；组装继续


class TestSeeding:
    def test_seeds_from_config_when_file_absent(self, tmp_path):
        plugin = make_plugin(
            tmp_path,
            config={
                "entries": [
                    {"order": 0, "role": "system", "source": "persona", "content": "", "enabled": True, "name": "人格"},
                    {"order": 10, "role": "system", "source": "text", "content": "", "enabled": True, "name": "自定义提示词"},
                ]
            },
        )
        names = [e["name"] for e in plugin.store.list_entries()]
        assert names == ["人格", "自定义提示词"]
        assert (tmp_path / "presets.json").exists()

    def test_no_reseed_when_file_exists(self, tmp_path):
        plugin = make_plugin(
            tmp_path,
            config={"entries": [{"order": 1, "name": "配置条目"}, {"order": 2, "name": "配置条目2"}]},
        )
        plugin.store.remove("配置条目")  # 用户删掉一条并落盘
        # 重新实例化（模拟插件重载）：文件已存在，配置不会回灌
        again = make_plugin(
            tmp_path,
            config={"entries": [{"order": 1, "name": "配置条目"}, {"order": 2, "name": "配置条目2"}]},
        )
        assert [e["name"] for e in again.store.list_entries()] == ["配置条目2"]

    def test_seed_skips_invalid_entries(self, tmp_path):
        plugin = make_plugin(
            tmp_path,
            config={"entries": [{"order": 1, "name": "好的"}, {"order": "坏", "name": "坏的"}]},
        )
        assert [e["name"] for e in plugin.store.list_entries()] == ["好的"]
