"""内置块切分引擎（M4）：把 ``{{native_system}}`` 整块快照按 AstrBot 内置注入块切分为独立变量。

标记注册表的每个条目 = (变量名, 识别标记元组)。标记文本全部从 AstrBot v4.28
源码核实（`astrbot/core/astr_main_agent_resources.py` 与 `astrbot/core/astr_main_agent.py`，
2026-09 经 cdn.jsdelivr.net/gh/AstrBotDevs/AstrBot@master 核对）：

======================  ============================================  ==========================
变量名                  识别标记（块开头特征）                          源码出处
======================  ============================================  ==========================
native_safety           You are running in Safe Mode.                  LLM_SAFETY_MODE_SYSTEM_PROMPT
native_local_mode       You have access to the host local environment  _build_local_mode_prompt()
native_genui            [ChatUI HTML GenUI]                            CHATUI_INLINE_GENUI_SYSTEM_PROMPT
native_persona          # Persona Instructions                         persona 注入（标题+人设全文一块）
native_default_persona  You are a calm, patient friend                 CHATUI_SPECIAL_DEFAULT_PERSONA_PROMPT
native_skills           ## Skills                                      build_skills_prompt() 输出开头
native_router           （无固定标记，见下）                            router_prompt 构造处
native_sandbox          You have access to a sandboxed environment     SANDBOX_MODE_PROMPT
native_websearch        Always cite web search results                 WEB_SEARCH_CITATION_PROMPT 开头
native_tools            When using tools: / You MUST NOT return an     TOOL_CALL_PROMPT /
                        empty response（两种 tool_schema_mode）         TOOL_CALL_PROMPT_SKILLS_LIKE_MODE
native_live             You are in a real-time conversation            LIVE_MODE_SYSTEM_PROMPT
native_other            （无标记，兜底）                                首个已知块之前的全部内容
======================  ============================================  ==========================

关于 ``native_router``：源码核实 `router_prompt` 来自用户配置
（`subagent_orchestrator.router_system_prompt`，经 ``+= f"\\n{router_prompt}\\n"`` 注入），
没有稳定的文本标记可识别，故注册表标记留空 → 该变量恒为空串，实际注入的
路由提示按区间算法归入相邻已知块或 ``native_other``（内容不丢失）。

已知限制（任务书明示接受）：

- 切分依赖标记文本。AstrBot 大版本更新若修改内置提示词措辞，需核对注册表——
  未匹配内容不会丢失（区间拼接覆盖全串），只是块归属变化、归入相邻块或 native_other。
- 用户 persona 内容中若恰好包含其他块的标记文本（首次出现位置），可能误切——
  拼接结果仍完整，仅块归属可能偏差。
- 其他插件（living 等）向 system_prompt 追加的内容无稳定标记，按区间归入
  前一个已知块；只有位于首个已知块之前的内容才归 ``native_other``。
"""

from __future__ import annotations

NATIVE_BLOCK_REGISTRY: list[tuple[str, tuple[str, ...]]] = [
    # (变量名, 识别标记元组)：任一标记的首次出现位置即块起点；取最早命中者。
    ("native_safety", ("You are running in Safe Mode.",)),
    ("native_genui", ("[ChatUI HTML GenUI]",)),
    ("native_persona", ("# Persona Instructions",)),
    ("native_default_persona", ("You are a calm, patient friend",)),
    ("native_skills", ("## Skills",)),
    # router_prompt 为用户配置文本，无稳定标记：标记留空 → 块恒不存在（变量恒为空串）。
    ("native_router", ()),
    ("native_sandbox", ("You have access to a sandboxed environment",)),
    ("native_local_mode", ("You have access to the host local environment",)),
    ("native_websearch", ("Always cite web search results",)),
    ("native_tools", (
        "When using tools:",  # tool_schema_mode == "full"
        "You MUST NOT return an empty response",  # tool_schema_mode == "skills_like"
    )),
    ("native_live", ("You are in a real-time conversation",)),
]

NATIVE_OTHER = "native_other"
NATIVE_SYSTEM = "native_system"

PREVIEW_PLACEHOLDER = "（发消息时替换为 AstrBot 原生内容）"
"""预览上下文中 native_* 变量的占位说明（preview 无真实 req，见任务书需求 4）。"""


def native_variable_names() -> tuple[str, ...]:
    """全部 native 系变量名（含整块 native_system 与兜底 native_other）。"""
    return (NATIVE_SYSTEM, *(var for var, _ in NATIVE_BLOCK_REGISTRY), NATIVE_OTHER)


def split_native_system(native_system: str) -> dict[str, str]:
    """把原生 system_prompt 快照切分为各内置块变量。

    算法（任务书 M4 需求 1）：

    1. 对注册表中每个标记在快照中查**首次出现位置**（`str.find`），任一标记
       命中即定位该变量块起点（多标记取最早命中）；找不到则该变量为空串；
    2. 所有命中位置升序排序；相邻两个位置之间的文本区间归**前一个**变量；
       最后一个位置到字符串末尾归最后一个变量；
    3. 首个命中位置之前的内容（头部）归 ``native_other``；一个标记都没命中时
       整串归 ``native_other``；
    4. 每块 strip 首尾空白后作为变量值；strip 后为空的块值为空串。

    切分区间并集严格覆盖全串（拼接完整性）：内容不会因切分丢失，最多发生
    块归属偏差（见模块 docstring 已知限制）。
    """
    blocks: dict[str, str] = {var: "" for var, _ in NATIVE_BLOCK_REGISTRY}
    blocks[NATIVE_OTHER] = ""
    for var, raw in _split_raw(native_system or ""):
        blocks[var] = raw.strip()
    return blocks


def _split_raw(text: str) -> list[tuple[str, str]]:
    """按标记位置切出 (变量名, 原始区间文本) 列表（含 native_other 头部区间）。

    区间首尾相接且并集覆盖全串：``"".join(raw for _, raw in _split_raw(t)) == t``。
    """
    found: list[tuple[int, str]] = []
    for var, markers in NATIVE_BLOCK_REGISTRY:
        positions = [text.find(marker) for marker in markers]
        positions = [p for p in positions if p >= 0]
        if positions:
            found.append((min(positions), var))
    if not found:
        return [(NATIVE_OTHER, text)]

    found.sort(key=lambda item: item[0])
    spans: list[tuple[str, str]] = [(NATIVE_OTHER, text[: found[0][0]])]
    for index, (start, var) in enumerate(found):
        end = found[index + 1][0] if index + 1 < len(found) else len(text)
        spans.append((var, text[start:end]))
    return spans
