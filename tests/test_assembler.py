"""组装引擎测试 + 端到端集成测试（mock ProviderRequest）。"""

import asyncio

from astrbot_plugin_prompt_preset.core.assembler import PromptAssembler
from tests.helpers import make_store


def do_assemble(assembler, req, persona_text=""):
    return asyncio.run(assembler.assemble(req, persona_text))


def make_assembler(tmp_path, entries, context=None):
    store = make_store(tmp_path, entries)
    return PromptAssembler(store, context=context)


class TestOrdering:
    def test_sorted_by_order(self, tmp_path):
        asm = make_assembler(
            tmp_path,
            [
                {"order": 10, "role": "user", "name": "后", "content": "后"},
                {"order": 0, "role": "user", "name": "先", "content": "先"},
            ],
        )
        req = type("Req", (), {"system_prompt": "", "contexts": []})()
        do_assemble(asm, req)
        assert [m["content"] for m in req.contexts] == ["先", "后"]

    def test_float_order_inserts_between(self, tmp_path):
        asm = make_assembler(
            tmp_path,
            [
                {"order": 0, "role": "user", "name": "a", "content": "a"},
                {"order": 10, "role": "user", "name": "c", "content": "c"},
                {"order": 5.5, "role": "user", "name": "b", "content": "b"},
            ],
        )
        req = type("Req", (), {"system_prompt": "", "contexts": []})()
        do_assemble(asm, req)
        assert [m["content"] for m in req.contexts] == ["a", "b", "c"]

    def test_same_order_keeps_insertion_order(self, tmp_path):
        asm = make_assembler(
            tmp_path,
            [
                {"order": 1, "role": "user", "name": "x", "content": "x"},
                {"order": 1, "role": "user", "name": "y", "content": "y"},
            ],
        )
        req = type("Req", (), {"system_prompt": "", "contexts": []})()
        do_assemble(asm, req)
        assert [m["content"] for m in req.contexts] == ["x", "y"]


class TestSources:
    def test_text_entry_variable_replaced(self, tmp_path):
        asm = make_assembler(
            tmp_path,
            [{"order": 0, "name": "t", "content": "你好，{{user_name}}"}],
            context={"user_name": "主人"},
        )
        req = type("Req", (), {"system_prompt": "", "contexts": []})()
        do_assemble(asm, req)
        assert req.system_prompt == "你好，主人"

    def test_text_entry_unknown_var_kept(self, tmp_path):
        asm = make_assembler(tmp_path, [{"order": 0, "name": "t", "content": "{{nope}}"}])
        req = type("Req", (), {"system_prompt": "", "contexts": []})()
        do_assemble(asm, req)
        assert req.system_prompt == "{{nope}}"

    def test_persona_entry_uses_persona_text(self, tmp_path):
        asm = make_assembler(
            tmp_path, [{"order": 0, "role": "system", "source": "persona", "name": "人格"}]
        )
        req = type("Req", (), {"system_prompt": "", "contexts": []})()
        do_assemble(asm, req, persona_text="你是凛。")
        assert req.system_prompt == "你是凛。"

    def test_persona_entry_empty_persona(self, tmp_path):
        asm = make_assembler(
            tmp_path, [{"order": 0, "source": "persona", "name": "人格"}]
        )
        req = type("Req", (), {"system_prompt": "旧提示词", "contexts": []})()
        do_assemble(asm, req, persona_text="")
        assert req.system_prompt == ""

    def test_persona_entry_respects_entry_role(self, tmp_path):
        asm = make_assembler(
            tmp_path, [{"order": 0, "role": "user", "source": "persona", "name": "人格"}]
        )
        req = type("Req", (), {"system_prompt": "", "contexts": []})()
        do_assemble(asm, req, persona_text="你是凛。")
        assert req.contexts == [{"role": "user", "content": "你是凛。"}]
        assert req.system_prompt == ""

    def test_chat_history_expanded_in_place(self, tmp_path):
        history = [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "回答", "tool_calls": [{"id": "t1"}]},
        ]
        asm = make_assembler(
            tmp_path,
            [
                {"order": 0, "role": "system", "name": "开头", "content": "开头"},
                {"order": 1, "role": "user", "source": "chat_history", "name": "历史"},
                {"order": 2, "role": "user", "name": "收尾", "content": "收尾"},
            ],
        )
        req = type("Req", (), {"system_prompt": "旧", "contexts": list(history)})()
        do_assemble(asm, req)
        # 开头条目 role=system → 进 system_prompt；历史原样展开；收尾随后
        assert req.system_prompt == "开头"
        assert req.contexts == [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "回答", "tool_calls": [{"id": "t1"}]},
            {"role": "user", "content": "收尾"},
        ]

    def test_chat_history_empty_contexts(self, tmp_path):
        asm = make_assembler(
            tmp_path,
            [
                {"order": 0, "source": "chat_history", "role": "user", "name": "历史"},
                {"order": 1, "role": "user", "name": "t", "content": "文本"},
            ],
        )
        req = type("Req", (), {"system_prompt": "", "contexts": []})()
        do_assemble(asm, req)
        assert req.contexts == [{"role": "user", "content": "文本"}]


class TestTakeover:
    def test_system_entries_concatenated_in_order(self, tmp_path):
        asm = make_assembler(
            tmp_path,
            [
                {"order": 3, "role": "system", "name": "第二段", "content": "第二段"},
                {"order": 1, "role": "system", "name": "第一段", "content": "第一段"},
                {"order": 5, "role": "user", "name": "正文", "content": "正文"},
            ],
        )
        req = type("Req", (), {"system_prompt": "AstrBot 原生提示词", "contexts": []})()
        do_assemble(asm, req)
        assert req.system_prompt == "第一段\n\n第二段"
        assert req.contexts == [{"role": "user", "content": "正文"}]

    def test_native_system_prompt_discarded_even_without_system_entries(self, tmp_path):
        asm = make_assembler(
            tmp_path, [{"order": 0, "role": "user", "name": "t", "content": "文本"}]
        )
        req = type("Req", (), {"system_prompt": "原生", "contexts": []})()
        do_assemble(asm, req)
        assert req.system_prompt == ""

    def test_contexts_fully_replaced(self, tmp_path):
        asm = make_assembler(
            tmp_path, [{"order": 0, "role": "user", "name": "t", "content": "全新"}]
        )
        req = type("Req", (), {"system_prompt": "", "contexts": [{"role": "user", "content": "旧历史"}]})()
        do_assemble(asm, req)
        assert req.contexts == [{"role": "user", "content": "全新"}]


class TestNoOp:
    """空列表 / 全禁用 / 展开结果为空 → 不做任何操作，保留原生 req。"""

    def _req(self):
        return type(
            "Req", (), {"system_prompt": "原生提示词", "contexts": [{"role": "user", "content": "原生历史"}]}
        )()

    def test_empty_store_noop(self, tmp_path):
        asm = make_assembler(tmp_path, [])
        req = self._req()
        assert do_assemble(asm, req) is False
        assert req.system_prompt == "原生提示词"
        assert req.contexts == [{"role": "user", "content": "原生历史"}]

    def test_all_disabled_noop(self, tmp_path):
        asm = make_assembler(
            tmp_path,
            [
                {"order": 0, "name": "关1", "content": "x", "enabled": False},
                {"order": 1, "name": "关2", "content": "y", "enabled": False},
            ],
        )
        req = self._req()
        assert do_assemble(asm, req) is False
        assert req.system_prompt == "原生提示词"
        assert req.contexts == [{"role": "user", "content": "原生历史"}]

    def test_chat_history_only_with_empty_contexts_noop(self, tmp_path):
        asm = make_assembler(
            tmp_path, [{"order": 0, "source": "chat_history", "name": "历史"}]
        )
        req = type("Req", (), {"system_prompt": "原生提示词", "contexts": []})()
        assert do_assemble(asm, req) is False
        assert req.system_prompt == "原生提示词"
        assert req.contexts == []

    def test_chat_history_expands_native_history(self, tmp_path):
        """仅一条 chat_history 条目 + 非空 contexts：原生历史被搬到 contexts，原生 system_prompt 被丢弃。"""
        asm = make_assembler(
            tmp_path, [{"order": 0, "role": "user", "source": "chat_history", "name": "历史"}]
        )
        req = self._req()
        assert do_assemble(asm, req) is True
        assert req.system_prompt == ""
        assert req.contexts == [{"role": "user", "content": "原生历史"}]


class TestPreview:
    def test_rows_sorted_and_truncated(self, tmp_path):
        asm = make_assembler(
            tmp_path,
            [
                {"order": 5, "name": "长文本", "content": "字" * 100},
                {"order": 1, "source": "persona", "name": "人格"},
            ],
        )
        rows = asm.preview(chat_history=[{"role": "user", "content": "hi"}], persona_text="人格全文")
        assert [r["name"] for r in rows] == ["人格", "长文本"]
        assert rows[0]["source"] == "persona"
        assert rows[0]["length"] == len("人格全文")
        assert rows[1]["length"] == 100
        assert len(rows[1]["snippet"]) == 50

    def test_preview_skips_disabled(self, tmp_path):
        asm = make_assembler(tmp_path, [{"order": 0, "name": "关", "content": "x", "enabled": False}])
        assert asm.preview() == []


class TestIntegration:
    def test_full_takeover_scenario(self, tmp_path):
        """端到端：原生 system_prompt + contexts（含 LivingMemory fake messages）+ persona，
        组装后最终 messages 的顺序与内容完全匹配条目配置。"""
        fake_messages = [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "mem1", "function": {"name": "memory_recall"}}]},
            {"role": "tool", "content": "记忆：主人喜欢喝茶", "tool_call_id": "mem1"},
        ]
        history = [
            {"role": "user", "content": "今天天气怎么样？"},
            *fake_messages,
            {"role": "assistant", "content": "晴，适合出门。"},
        ]
        persona_text = "你是凛，主人的AI伴侣。"
        store = make_store(
            tmp_path,
            [
                # 故意乱序添加，组装时必须按 order 重排
                {"order": 20, "role": "assistant", "name": "氛围", "content": "（{{bot_name}}轻声回应）"},
                {"order": 5, "role": "user", "source": "chat_history", "name": "对话历史"},
                {"order": 2, "role": "system", "name": "思考框架",
                 "content": "【思考框架】和{{user_name}}对话时：①回到身份 ②理解意图 ③带入心情"},
                {"order": 0, "role": "system", "source": "persona", "name": "人格"},
            ],
        )
        assembler = PromptAssembler(
            store, context={"user_name": "主人", "bot_name": "凛", "time": "12:00", "date": "2026-09-08", "datetime": "2026-09-08 12:00"}
        )
        req = type("Req", (), {})()
        req.system_prompt = "You are AstrBot, a helpful assistant."  # AstrBot 原生注入，必须被丢弃
        req.contexts = list(history)
        handled = asyncio.run(assembler.assemble(req, persona_text))
        assert handled is True

        # 最终 system_prompt：两条 system 条目按 order 拼接
        assert req.system_prompt == (
            "你是凛，主人的AI伴侣。\n\n"
            "【思考框架】和主人对话时：①回到身份 ②理解意图 ③带入心情"
        )
        # 最终 contexts：条目逐字匹配（chat_history 展开含 LivingMemory fake messages）
        assert req.contexts == [
            {"role": "user", "content": "今天天气怎么样？"},
            *fake_messages,
            {"role": "assistant", "content": "晴，适合出门。"},
            {"role": "assistant", "content": "（凛轻声回应）"},
        ]

    def test_via_hook_full_path(self, tmp_path):
        """钩子路径集成：make_plugin → on_llm_request → req 被接管。"""
        from tests.helpers import make_plugin, run_hook

        persona = {"prompt": "你是凛。", "name": "凛"}
        plugin = make_plugin(
            tmp_path,
            persona=persona,
            config={"variables": {"user_name": "主人", "bot_name": "凛"}},
        )
        plugin.store.add({"order": 0, "role": "system", "name": "人格", "source": "persona"})
        plugin.store.add({"order": 1, "role": "system", "name": "问候", "content": "你好，{{user_name}}"})
        req = type("Req", (), {})()
        req.system_prompt = "原生"
        req.contexts = [{"role": "user", "content": "历史消息"}]
        run_hook(plugin, req)
        assert req.system_prompt == "你是凛。\n\n你好，主人"
        # 无非 system 条目 → contexts 被完全替换为空列表
        assert req.contexts == []
