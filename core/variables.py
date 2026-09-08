"""变量替换引擎。

把文本中的 ``{{key}}`` 替换为上下文中的值；未知变量保留原样（不替换、不报错）。
上下文由调用方注入（persona / user_name / bot_name / time / date / datetime
以及 _conf_schema.json ``variables`` 中的自定义变量）。
"""

from __future__ import annotations

import re

# 任务书规定：正则 {{(\w+)}} 匹配，查 dict 替换，找不到保留原样。
_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")


class VariableResolver:
    """``{{key}}`` 变量替换器。

    Args:
        context: 变量名 -> 值。值为 None 时按空字符串替换。
    """

    def __init__(self, context: dict | None = None):
        self._context: dict = dict(context or {})

    @property
    def context(self) -> dict:
        return dict(self._context)

    def update_context(self, context: dict) -> None:
        """合并注入新的变量（后者覆盖前者）。"""
        self._context.update(context or {})

    def resolve(self, text: str) -> str:
        """替换 text 中所有已知变量，返回替换后的文本。"""
        if not text:
            return text or ""

        def _replace(match: re.Match) -> str:
            key = match.group(1)
            if key not in self._context:
                return match.group(0)  # 未知变量保留原样
            value = self._context[key]
            return "" if value is None else str(value)

        return _VAR_PATTERN.sub(_replace, text)
