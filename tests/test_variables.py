"""变量替换引擎测试。"""

from astrbot_plugin_prompt_preset.core.variables import VariableResolver


class TestKnownVariables:
    def test_simple_replacement(self):
        r = VariableResolver({"user_name": "主人"})
        assert r.resolve("早上好，{{user_name}}") == "早上好，主人"

    def test_persona_variable(self):
        r = VariableResolver({"persona": "你是凛。"})
        assert r.resolve("全文：{{persona}}") == "全文：你是凛。"

    def test_multiple_occurrences(self):
        r = VariableResolver({"bot_name": "凛"})
        assert r.resolve("{{bot_name}}{{bot_name}}") == "凛凛"

    def test_multiple_different_vars(self):
        r = VariableResolver({"date": "2026-09-08", "time": "12:30"})
        assert r.resolve("{{date}} {{time}}") == "2026-09-08 12:30"

    def test_multiline_content(self):
        r = VariableResolver({"user_name": "主人"})
        text = "第一行 {{user_name}}\n第二行 {{user_name}}"
        assert r.resolve(text) == "第一行 主人\n第二行 主人"

    def test_none_value_resolves_empty(self):
        r = VariableResolver({"persona": None})
        assert r.resolve("a{{persona}}b") == "ab"

    def test_non_string_value_coerced(self):
        r = VariableResolver({"count": 3})
        assert r.resolve("x{{count}}") == "x3"


class TestUnknownVariables:
    def test_unknown_kept_verbatim(self):
        r = VariableResolver({"a": "1"})
        assert r.resolve("{{unknown_var}}") == "{{unknown_var}}"

    def test_mixed_known_unknown(self):
        r = VariableResolver({"user_name": "主人"})
        assert r.resolve("{{user_name}} {{nope}}") == "主人 {{nope}}"

    def test_nested_braces_not_replaced(self):
        # 外层 "{{outer {{inner}} }}" 不是合法变量，保留原样；内层照常替换
        r = VariableResolver({"inner": "X"})
        assert r.resolve("{{outer {{inner}} }}") == "{{outer X }}"


class TestEdgeCases:
    def test_empty_text(self):
        assert VariableResolver({"a": "1"}).resolve("") == ""

    def test_plain_text_untouched(self):
        r = VariableResolver({"a": "1"})
        assert r.resolve("没有任何变量的普通文本") == "没有任何变量的普通文本"

    def test_single_braces_untouched(self):
        r = VariableResolver({"user_name": "主人"})
        assert r.resolve("JSON 示例 {user_name} {a}") == "JSON 示例 {user_name} {a}"

    def test_empty_context_keeps_everything(self):
        r = VariableResolver({})
        assert r.resolve("{{time}} {{date}}") == "{{time}} {{date}}"

    def test_update_context_merges(self):
        r = VariableResolver({"a": "1"})
        r.update_context({"b": "2"})
        assert r.resolve("{{a}}{{b}}") == "12"
