"""M3 变量扩展测试：``{{native_system}}`` / ``{{memories}}`` / extract_memories。

对应任务书 docs/task_m3_变量扩展.md 的四组需求：

1. ``{{native_system}}`` 展开（组装覆盖前捕获原生 system_prompt）；
2. ``{{memories}}`` 展开（从 req.contexts 提取 LivingMemory 记忆）；
3. ``extract_memories`` 单元测试；
4. M1/M2 回归（条目不引用新变量时组装结果与 M1 完全一致 + 全量套件）。

另含 TestPreviewWiring：面板 preview 端点的 context_provider 接线回归
（PromptPresetAPI 约定 async 无参 provider；见 m3_report.md §2）。
"""

import asyncio

from astrbot_plugin_prompt_preset.core.assembler import PromptAssembler
from astrbot_plugin_prompt_preset.core.variables import (
    LIVING_MEMORY_TOOL_ID_PREFIX,
    extract_memories,
)
from tests.helpers import make_plugin, make_store, run_hook


def run(coro):
    return asyncio.run(coro)


def make_assembler(tmp_path, entries, context=None):
    store = make_store(tmp_path, entries)
    return PromptAssembler(store, context=context)


def fake_memory_message(content, call_id="recall_long_term_memory_001"):
    """按 LivingMemory 的注入形态构造伪工具消息（role=tool + 约定前缀 id）。"""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "function": {"name": "recall_long_term_memory"}}],
    }, {
        "role": "tool",
        "tool_call_id": call_id,
        "content": content,
    }


NATIVE_SYSTEM = "安全模式提示\nPersona Instructions\n你是 AstrBot。"


# ---------------------------------------------------------------------------
# 测试 1：{{native_system}} 展开
# ---------------------------------------------------------------------------

class TestNativeSystem:
    def test_entry_reference_expands_to_native_system_prompt(self, tmp_path):
        asm = make_assembler(
            tmp_path,
            [{"order": 0, "name": "引用原生", "content": "以下是内置提示词：\n{{native_system}}"}],
        )
        req = type("Req", (), {"system_prompt": NATIVE_SYSTEM, "contexts": []})()
        handled = run(asm.assemble(req, persona_text=""))
        assert handled is True
        assert "以下是内置提示词：\n" in req.system_prompt
        assert req.system_prompt.endswith(NATIVE_SYSTEM)  # 原生 system_prompt 全文被捕获进条目

    def test_reference_via_user_role_entry_lands_in_contexts(self, tmp_path):
        asm = make_assembler(
            tmp_path,
            [{"order": 0, "role": "user", "name": "引用原生", "content": "{{native_system}}"}],
        )
        req = type("Req", (), {"system_prompt": NATIVE_SYSTEM, "contexts": []})()
        run(asm.assemble(req, persona_text=""))
        assert req.system_prompt == ""  # 条目是 user 角色 → 原生 system_prompt 仍被丢弃
        assert req.contexts == [{"role": "user", "content": NATIVE_SYSTEM}]

    def test_no_reference_keeps_m1_semantics_native_discarded(self, tmp_path):
        """不引用 {{native_system}} 时与 M1 完全一致：原生 system_prompt 被覆盖丢弃。"""
        asm = make_assembler(
            tmp_path,
            [{"order": 0, "name": "普通条目", "content": "只跟 persona 有关：{{persona}}"}],
        )
        req = type("Req", (), {"system_prompt": NATIVE_SYSTEM, "contexts": []})()
        run(asm.assemble(req, persona_text="你是凛。"))
        assert req.system_prompt == "只跟 persona 有关：你是凛。"
        assert NATIVE_SYSTEM not in req.system_prompt
        assert req.contexts == []

    def test_empty_native_system_expands_to_empty(self, tmp_path):
        asm = make_assembler(
            tmp_path,
            [{"order": 0, "name": "引用原生", "content": "前缀[{{native_system}}]后缀"}],
        )
        req = type("Req", (), {"system_prompt": "", "contexts": []})()
        run(asm.assemble(req, persona_text=""))
        assert req.system_prompt == "前缀[]后缀"


# ---------------------------------------------------------------------------
# 测试 2：{{memories}} 展开
# ---------------------------------------------------------------------------

class TestMemories:
    def test_entry_reference_expands_memory_texts(self, tmp_path):
        pair = fake_memory_message('["主人昨天带我去海边", "主人喜欢喝茶"]')
        asm = make_assembler(
            tmp_path,
            [{"order": 0, "name": "引用记忆", "content": "我最近经历了：{{memories}}"}],
        )
        req = type("Req", (), {"system_prompt": "", "contexts": [pair[0], pair[1]]})()
        run(asm.assemble(req, persona_text=""))
        assert "我最近经历了：" in req.system_prompt
        assert "主人昨天带我去海边" in req.system_prompt
        assert "主人喜欢喝茶" in req.system_prompt

    def test_no_fake_messages_expands_to_empty(self, tmp_path):
        asm = make_assembler(
            tmp_path,
            [{"order": 0, "name": "引用记忆", "content": "我最近经历了：{{memories}}"}],
        )
        req = type(
            "Req",
            (),
            {"system_prompt": "", "contexts": [{"role": "user", "content": "早"}]},
        )()
        run(asm.assemble(req, persona_text=""))
        assert req.system_prompt == "我最近经历了："  # 展开为空串

    def test_non_memory_tool_messages_ignored(self, tmp_path):
        other_tool = {"role": "tool", "tool_call_id": "weather_001", "content": '["天气晴"]'}
        plain_user = {"role": "user", "content": "普通消息"}
        pair = fake_memory_message('["真实记忆"]')
        asm = make_assembler(
            tmp_path,
            [{"order": 0, "name": "引用记忆", "content": "{{memories}}"}],
        )
        req = type(
            "Req", (), {"system_prompt": "", "contexts": [other_tool, plain_user, *pair]}
        )()
        run(asm.assemble(req, persona_text=""))
        assert req.system_prompt == "真实记忆"

    def test_prefix_match_is_required(self, tmp_path):
        """tool_call_id 不以 recall_long_term_memory 开头的 tool 消息不算记忆。"""
        similar = {
            "role": "tool",
            "tool_call_id": "my_recall_long_term_memory_x",  # 前缀不在开头
            "content": '["不算记忆"]',
        }
        asm = make_assembler(
            tmp_path,
            [{"order": 0, "name": "引用记忆", "content": "[{{memories}}]"}],
        )
        req = type("Req", (), {"system_prompt": "", "contexts": [similar]})()
        run(asm.assemble(req, persona_text=""))
        assert req.system_prompt == "[]"

    def test_prefix_constant_matches_task_book(self):
        assert LIVING_MEMORY_TOOL_ID_PREFIX == "recall_long_term_memory"


# ---------------------------------------------------------------------------
# 测试 3：extract_memories 单元测试
# ---------------------------------------------------------------------------

class TestExtractMemories:
    def test_json_array_content_extracted_and_joined(self):
        pair = fake_memory_message('["记忆A", "记忆B"]')
        contexts = [pair[0], pair[1]]
        assert extract_memories(contexts) == "记忆A\n记忆B"

    def test_content_as_list_extracted(self):
        msg = {"role": "tool", "tool_call_id": "recall_long_term_memory_1",
               "content": ["直接是列表", {"memory": "字典记忆"}]}
        assert extract_memories([msg]) == "直接是列表\n字典记忆"

    def test_invalid_json_kept_verbatim(self):
        msg = {"role": "tool", "tool_call_id": "recall_long_term_memory_1",
               "content": "这不是JSON{格式"}
        assert extract_memories([msg]) == "这不是JSON{格式"

    def test_plain_text_content_kept(self):
        msg = {"role": "tool", "tool_call_id": "recall_long_term_memory_1",
               "content": "主人周末去了公园"}
        assert extract_memories([msg]) == "主人周末去了公园"

    def test_dict_items_take_memory_text_content_fact_fields(self):
        msg = {
            "role": "tool",
            "tool_call_id": "recall_long_term_memory_1",
            "content": '[{"memory": "首选"}, {"text": "次选"}, {"content": "再次"}, {"fact": "末选"}]',
        }
        assert extract_memories([msg]) == "首选\n次选\n再次\n末选"

    def test_dict_without_known_fields_falls_back_to_json(self):
        msg = {
            "role": "tool",
            "tool_call_id": "recall_long_term_memory_1",
            "content": '[{"unknown": "字段", "n": 1}]',
        }
        extracted = extract_memories([msg])
        assert '"unknown": "字段"' in extracted and '"n": 1' in extracted

    def test_json_object_single_item(self):
        msg = {"role": "tool", "tool_call_id": "recall_long_term_memory_1",
               "content": '{"memory": "单条对象记忆"}'}
        assert extract_memories([msg]) == "单条对象记忆"

    def test_empty_list_returns_empty_string(self):
        msg = {"role": "tool", "tool_call_id": "recall_long_term_memory_1", "content": "[]"}
        assert extract_memories([msg]) == ""

    def test_empty_and_none_contents_skipped(self):
        empty = {"role": "tool", "tool_call_id": "recall_long_term_memory_1", "content": ""}
        none = {"role": "tool", "tool_call_id": "recall_long_term_memory_2", "content": None}
        pair = fake_memory_message('["有效记忆"]')
        assert extract_memories([empty, none, *pair]) == "有效记忆"

    def test_multiple_messages_joined_in_order(self):
        p1 = fake_memory_message('["早上的记忆"]', "recall_long_term_memory_1")
        p2 = fake_memory_message('["晚上的记忆"]', "recall_long_term_memory_2")
        assert extract_memories([*p1, *p2]) == "早上的记忆\n晚上的记忆"

    def test_empty_contexts_return_empty_string(self):
        assert extract_memories([]) == ""
        assert extract_memories(None) == ""

    def test_non_string_items_coerced(self):
        msg = {"role": "tool", "tool_call_id": "recall_long_term_memory_1",
               "content": '[42, null, "文本"]'}
        assert extract_memories([msg]) == "42\n文本"


# ---------------------------------------------------------------------------
# 测试 4：M1 语义回归 + 完整钩子路径
# ---------------------------------------------------------------------------

class TestM1SemanticsUnchanged:
    def test_assembly_identical_when_vars_unreferenced(self, tmp_path):
        """条目不含新变量时，组装结果与 M1 逐字节一致（原生照旧丢弃）。"""
        history = [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "回答"},
        ]
        asm = make_assembler(
            tmp_path,
            [
                {"order": 1, "role": "system", "name": "框架", "content": "【框架】"},
                {"order": 2, "role": "user", "source": "chat_history", "name": "历史"},
            ],
        )
        req = type("Req", (), {"system_prompt": NATIVE_SYSTEM, "contexts": list(history)})()
        run(asm.assemble(req, persona_text="你是凛。"))
        assert req.system_prompt == "【框架】"
        assert req.contexts == history  # 原样展开，无额外注入

    def test_via_hook_with_both_new_vars(self, tmp_path):
        """完整钩子路径：native_system 与 memories 同时被条目引用。"""
        persona = {"prompt": "你是凛。", "name": "凛"}
        plugin = make_plugin(tmp_path, persona=persona)
        plugin.store.add({"order": 0, "role": "system", "name": "人格", "source": "persona"})
        plugin.store.add(
            {
                "order": 1,
                "role": "system",
                "name": "混合",
                "content": "[{{native_system}}]\n最近：{{memories}}",
            }
        )
        pair = fake_memory_message('["主人养了一只猫"]')
        req = type("Req", (), {})()
        req.system_prompt = "AstrBot 原生提示词"
        req.contexts = [{"role": "user", "content": "在吗"}, *pair]
        run_hook(plugin, req)
        # 两条 system 消息以空行拼接（SYSTEM_JOIN）
        assert req.system_prompt == (
            "你是凛。\n\n[AstrBot 原生提示词]\n最近：主人养了一只猫"
        )
        # contexts 被完全替换（无 chat_history 条目 → 空）
        assert req.contexts == []


# ---------------------------------------------------------------------------
# 面板 preview 的 context_provider 接线（PromptPresetAPI 约定：async 无参）
# ---------------------------------------------------------------------------

class TestPreviewWiring:
    def test_api_preview_returns_rows(self, tmp_path):
        """preview 端点应返回 rows 而不是"内部错误"（provider 接线回归）。"""
        plugin = make_plugin(tmp_path, persona={"prompt": "你是凛。", "name": "凛"})
        plugin.store.add({"order": 0, "role": "system", "name": "人格", "source": "persona"})
        result = run(plugin._api_preview())
        assert result["status"] == "ok", f"preview 应成功，实际：{result}"
        assert result["data"]["count"] == 1
        assert result["data"]["rows"][0]["snippet"] == "你是凛。"

    def test_api_preview_never_breaks_on_provider(self, tmp_path):
        """provider 返回的上下文须含 persona 键（长度统计与 persona 行依赖它）。"""
        plugin = make_plugin(tmp_path, persona={"prompt": "人格全文", "name": "凛"})
        result = run(plugin._api_preview())
        assert result["status"] == "ok"
        assert result["data"]["persona_length"] == len("人格全文")
