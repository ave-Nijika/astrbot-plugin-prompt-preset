"""WebUI 面板的后端 API 核心（框架无关，便于独立测试）。

M2 调研结论（详见 docs/m2_report.md）：AstrBot ≥4.24.2 提供官方"插件 Pages"
机制——后端 API 通过 ``context.register_web_api(route, handler, methods, desc)``
注册（route 必须带插件名前缀，支持 ``<name>`` 动态段）；dashboard 的 JWT 鉴权
自动覆盖这些路由；前端页面以受限 iframe 加载，经 ``window.AstrBotPluginPage``
bridge 调用后端（bridge 只提供 GET/POST，因此更新/删除/重排序额外注册 POST
别名路由）。

本模块只承载纯业务逻辑：入参是已解析的 Python 对象，出参是可直接 JSON 化的
dict；客户端错误抛 :class:`ApiError`。与 Quart/FastAPI/request 对象完全解耦，
底层复用 M1 的 EntryStore / PromptAssembler。
"""

from __future__ import annotations

from .core.assembler import PromptAssembler
from .core.entry_store import EntryStore, EntryValidationError

REORDER_SPACING = 10.0
"""拖拽重排序后的等间距 order 步长（与 _conf_schema 默认条目 0/10 一致）。"""


class ApiError(Exception):
    """客户端错误（适配层会转成 error_response + HTTP 状态码）。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class PromptPresetAPI:
    """面板后端：条目 CRUD / 重排序 / 变量 / 组装预览。

    Args:
        store: M1 的 EntryStore。
        assembler: M1 的 PromptAssembler（preview 用）。
        get_variables: 同步callable，返回当前自定义变量 dict（来自插件配置）。
        set_variables: callable(dict)，把新变量写入插件配置并持久化。
        context_provider: async callable，返回完整变量上下文
            （含 persona/time/date/datetime，与钩子组装时一致）。
    """

    def __init__(
        self,
        store: EntryStore,
        assembler: PromptAssembler,
        get_variables,
        set_variables,
        context_provider,
    ):
        self.store = store
        self.assembler = assembler
        self._get_variables = get_variables
        self._set_variables = set_variables
        self._context_provider = context_provider

    # ------------------------------------------------------------------
    # 条目
    # ------------------------------------------------------------------
    async def entries_get(self) -> dict:
        """全部条目（含禁用），按 order 升序。"""
        return {"entries": self.store.list_entries()}

    async def entries_post(self, payload) -> dict:
        """新增条目，body = 完整条目 JSON（可缺省字段，按 M1 规则补全）。"""
        entry = self._expect_dict(payload, "条目数据必须是 JSON 对象")
        try:
            created = self.store.add(entry)
        except EntryValidationError as e:
            raise ApiError(str(e)) from None
        return {"entry": created}

    async def entry_put(self, item_id: str, payload) -> dict:
        """更新条目（部分字段 patch）。"""
        patch = self._expect_dict(payload, "更新数据必须是 JSON 对象")
        patch = {k: v for k, v in patch.items() if k != "id"}
        updated = self.store.update(item_id, patch)
        if not updated:
            raise ApiError(f"条目不存在：{item_id}", status_code=404)
        return {"entry": updated}

    async def entry_delete(self, item_id: str) -> dict:
        """删除条目。"""
        removed = self.store.remove(item_id)
        if not removed:
            raise ApiError(f"条目不存在：{item_id}", status_code=404)
        return {"removed": removed["name"], "id": item_id}

    async def entries_reorder(self, payload) -> dict:
        """按给定 id 顺序重写所有条目的 order（等间距重编号）。

        body 可以是 ``[id1, id2, ...]`` 或 ``{"ids": [...]}``。
        id 列表必须覆盖全部条目（面板拖拽总是提交完整列表）。
        """
        if isinstance(payload, dict):
            ids = payload.get("ids")
        else:
            ids = payload
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ApiError("body 需为有序 id 列表（[...] 或 {\"ids\": [...]}）")
        if len(set(ids)) != len(ids):
            raise ApiError("id 列表中有重复项")

        entries = {e["id"]: e for e in self.store.list_entries()}
        missing = [i for i in ids if i not in entries]
        if missing:
            raise ApiError(f"未知条目 id：{', '.join(missing)}")
        leftover = sorted(set(entries) - set(ids))
        if leftover:
            raise ApiError(f"id 列表缺少条目：{', '.join(leftover)}")

        for index, item_id in enumerate(ids):
            self.store.update(item_id, {"order": float(index) * REORDER_SPACING})
        return {"entries": self.store.list_entries()}

    # ------------------------------------------------------------------
    # 自定义变量
    # ------------------------------------------------------------------
    async def variables_get(self) -> dict:
        return {"variables": dict(self._get_variables() or {})}

    async def variables_put(self, payload) -> dict:
        if isinstance(payload, dict) and "variables" in payload:
            payload = payload["variables"]
        if not isinstance(payload, dict):
            raise ApiError("body 需为变量对象（{key: value} 或 {\"variables\": {...}}）")
        clean: dict = {}
        for key, value in payload.items():
            if not isinstance(key, str) or not key.strip():
                raise ApiError(f"变量名不合法：{key!r}")
            clean[key.strip()] = "" if value is None else value
        self._set_variables(clean)
        return {"variables": dict(self._get_variables() or {})}

    # ------------------------------------------------------------------
    # 组装预览
    # ------------------------------------------------------------------
    async def preview_get(self, chat_history: list | None = None) -> dict:
        """当前组装结果预览（与钩子实际组装同一套 assembler/变量上下文）。"""
        var_context = dict(await self._context_provider() or {})
        self.assembler.set_context(var_context)
        rows = self.assembler.preview(
            chat_history=chat_history or [],
            persona_text=var_context.get("persona", ""),
        )
        return {
            "rows": rows,
            "count": len(rows),
            "persona_length": len(var_context.get("persona", "")),
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _expect_dict(payload, message: str) -> dict:
        if not isinstance(payload, dict):
            raise ApiError(message)
        return payload
