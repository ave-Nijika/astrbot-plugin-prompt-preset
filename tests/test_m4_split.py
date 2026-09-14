"""M4 切分引擎单元测试（core/splitter.py）。"""

from astrbot_plugin_prompt_preset.core.splitter import (
    NATIVE_BLOCK_REGISTRY,
    _split_raw,
    native_variable_names,
    split_native_system,
)


def snapshot() -> str:
    """多块共存的典型原生快照（每块用真实注入分隔形态拼接）。"""
    return (
        "You are running in Safe Mode.\n\n"
        "Follow these rules:\n"
        "- Be nice.\n"
        "\n"
        "# Persona Instructions\n\n"
        "你是凛。\n"
        "\n"
        "## Skills\n\n"
        "You have specialized skills.\n"
        "\n"
        "You have access to a sandboxed environment and can execute shell commands.\n"
        "\n"
        "When using tools: never return an empty response.\n"
        "\n"
        "Always cite web search results you rely on.\n"
    )


class TestRegistry:
    def test_all_task_book_variables_registered(self):
        names = [var for var, _ in NATIVE_BLOCK_REGISTRY]
        assert set(names) == {
            "native_safety",
            "native_local_mode",
            "native_genui",
            "native_persona",
            "native_default_persona",
            "native_skills",
            "native_router",
            "native_sandbox",
            "native_websearch",
            "native_tools",
            "native_live",
        }

    def test_router_has_no_stable_marker(self):
        # 源码核实：router_prompt 是用户配置（subagent_orchestrator.router_system_prompt），
        # 无固定标记 → 标记留空，变量恒为空串，内容归相邻块/native_other。
        markers = dict(NATIVE_BLOCK_REGISTRY)["native_router"]
        assert markers == ()

    def test_tools_has_two_mode_markers(self):
        markers = dict(NATIVE_BLOCK_REGISTRY)["native_tools"]
        assert markers == (
            "When using tools:",
            "You MUST NOT return an empty response",
        )

    def test_native_variable_names_includes_system_and_other(self):
        names = native_variable_names()
        assert names[0] == "native_system"
        assert names[-1] == "native_other"
        assert "memories" not in names  # memories 属于既有变量，不在 native 系


class TestSplit:
    def test_blocks_split_by_markers(self):
        blocks = split_native_system(snapshot())
        assert blocks["native_safety"].startswith("You are running in Safe Mode.")
        assert "Be nice." in blocks["native_safety"]
        assert blocks["native_persona"] == "# Persona Instructions\n\n你是凛。"
        assert blocks["native_skills"].startswith("## Skills")
        assert blocks["native_sandbox"].startswith("You have access to a sandboxed environment")
        assert blocks["native_tools"].startswith("When using tools:")
        assert blocks["native_websearch"].startswith("Always cite web search results")

    def test_missing_blocks_are_empty_string(self):
        blocks = split_native_system(snapshot())
        assert blocks["native_genui"] == ""
        assert blocks["native_default_persona"] == ""
        assert blocks["native_local_mode"] == ""
        assert blocks["native_live"] == ""
        assert blocks["native_router"] == ""  # 无固定标记，恒为空串

    def test_no_markers_whole_text_is_native_other(self):
        text = "某插件注入的心境状态：今天心情很好。"
        blocks = split_native_system(text)
        assert blocks["native_other"] == text
        assert all(v == "" for k, v in blocks.items() if k != "native_other")

    def test_head_before_first_marker_is_native_other(self):
        text = "（插件前置的心境文本）\nYou are running in Safe Mode.\n\nrules here"
        blocks = split_native_system(text)
        assert blocks["native_other"] == "（插件前置的心境文本）"
        assert "rules here" in blocks["native_safety"]

    def test_blocks_are_stripped(self):
        text = "\n\n  You are running in Safe Mode.\n\n  rules  \n\n"
        blocks = split_native_system(text)
        assert blocks["native_safety"] == "You are running in Safe Mode.\n\n  rules"
        assert blocks["native_other"] == ""

    def test_empty_block_after_strip_is_empty_string(self):
        # 标记与下一个标记之间没有任何实质内容 → 该块值为空串
        text = "You are running in Safe Mode.\n# Persona Instructions\n\n{P}"
        blocks = split_native_system(text)
        assert blocks["native_safety"] == "You are running in Safe Mode."
        assert blocks["native_persona"] == "# Persona Instructions\n\n{P}"

    def test_tools_markers_match_either_mode(self):
        full = split_native_system("When using tools: never return an empty response.")
        assert full["native_tools"].startswith("When using tools:")
        skills_like = split_native_system(
            "You MUST NOT return an empty response, especially after invoking a tool."
        )
        assert skills_like["native_tools"].startswith("You MUST NOT return an empty response")

    def test_first_occurrence_wins_for_repeated_marker(self):
        text = (
            "# Persona Instructions\n\n{P}\n"
            "后面又提到一遍 # Persona Instructions 这个词组"
        )
        blocks = split_native_system(text)
        # 首次出现位置切块，重复提及仍在同一块内
        assert blocks["native_persona"].endswith("后面又提到一遍 # Persona Instructions 这个词组")

    def test_interference_text_without_exact_marker_does_not_mis_split(self):
        text = (
            "You are running in Safe Mode.\n\n"
            "本块正文提到「当使用工具时应当小心」以及 skills 的用法，"
            "但都不构成其他块的精确标记。\n"
        )
        blocks = split_native_system(text)
        assert blocks["native_safety"].endswith("但都不构成其他块的精确标记。")
        assert all(v == "" for k, v in blocks.items() if k not in ("native_safety", "native_other"))

    def test_empty_input(self):
        blocks = split_native_system("")
        assert blocks["native_other"] == ""
        assert all(v == "" for k, v in blocks.items())

    def test_none_input(self):
        assert split_native_system(None)["native_other"] == ""


class TestCompleteness:
    def test_raw_intervals_partition_whole_string(self):
        """切分区间并集严格覆盖全串：raw 区间按序拼接 == 原文（内容零丢失）。"""
        text = snapshot()
        spans = _split_raw(text)
        assert "".join(raw for _, raw in spans) == text

    def test_raw_intervals_contiguous(self):
        text = snapshot()
        spans = _split_raw(text)
        for (v1, raw1), (v2, raw2) in zip(spans, spans[1:]):
            assert text.index(raw1) + len(raw1) == text.index(raw2, text.index(raw1))

    def test_stripped_join_normalizes_back_to_original(self):
        """strip 后按空行拼接再归一化 == 原文归一化（语义等价的切分内幕）。"""
        from tests.helpers import normalize_prompt

        text = snapshot()
        blocks = split_native_system(text)
        # 按各块在原文中的出现顺序重建（等价性语义与块顺序相关）
        present = sorted((text.find(v), v) for v in blocks.values() if v)
        rebuilt = "\n\n".join(v for _, v in present)
        assert normalize_prompt(rebuilt) == normalize_prompt(text)
