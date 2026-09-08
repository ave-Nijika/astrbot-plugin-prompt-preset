"""M2 需求 D：WebUI 面板后端 API 测试。

三层覆盖：
1. 核心层 PromptPresetAPI（框架无关）——CRUD / reorder / variables / preview；
2. main.py 适配层——路由注册表与 method 分支、错误转换；
3. HTTP 层——FastAPI TestClient 走真实请求（任务书允许"或等效"，
   这里用与 main.py 注册表同构的 FastAPI 挂载做端到端验证）。
"""

import asyncio
import json

import pytest

from astrbot_plugin_prompt_preset.core.assembler import PromptAssembler
from astrbot_plugin_prompt_preset.core.entry_store import EntryStore
from astrbot_plugin_prompt_preset.dashboard_api import ApiError, PromptPresetAPI
from tests.helpers import FakeApiRequest, MockDashboardContext, make_plugin, make_store

PERSONA = "你是凛，主人的AI伴侣。"


def run(coro):
    return asyncio.run(coro)


class ApiHarness:
    """构造 PromptPresetAPI + 记录 set_variables 调用的测试台架。"""

    def __init__(self, tmp_path, variables=None):
        self.store = make_store(tmp_path)
        self.assembler = PromptAssembler(self.store)
        self.vars_box = {"variables": dict(variables or {"user_name": "主人", "bot_name": "凛"})}
        self.saved_variables = []
        self.context_box = {
            "persona": PERSONA,
            "time": "12:00",
            "date": "2026-09-09",
            "datetime": "2026-09-09 12:00",
        }

        def get_variables():
            return dict(self.vars_box["variables"])

        def set_variables(variables):
            self.vars_box["variables"] = dict(variables)
            self.saved_variables.append(dict(variables))

        async def context_provider():
            return {**self.context_box, **self.vars_box["variables"]}

        self.api = PromptPresetAPI(
            store=self.store,
            assembler=self.assembler,
            get_variables=get_variables,
            set_variables=set_variables,
            context_provider=context_provider,
        )


def add(api, **overrides):
    entry = {"order": 0, "name": "条目", "content": "内容"}
    entry.update(overrides)
    return api.store.add(entry)


class TestEntriesCrud:
    def test_entries_get_empty(self, tmp_path):
        data = run(ApiHarness(tmp_path).api.entries_get())
        assert data == {"entries": []}

    def test_entries_get_sorted_includes_disabled(self, tmp_path):
        h = ApiHarness(tmp_path)
        add(h.api, order=5, name="禁用的", enabled=False)
        add(h.api, order=1, name="启用的")
        data = run(h.api.entries_get())
        assert [e["name"] for e in data["entries"]] == ["启用的", "禁用的"]
        assert data["entries"][1]["enabled"] is False

    def test_entries_post_creates_and_persists(self, tmp_path):
        h = ApiHarness(tmp_path)
        data = run(
            h.api.entries_post(
                {"order": 3, "role": "user", "name": "新条目", "content": "正文", "enabled": True}
            )
        )
        created = data["entry"]
        assert created["name"] == "新条目" and created["id"]
        assert EntryStore(h.store.path).get("新条目")["content"] == "正文"

    def test_entries_post_applies_m1_defaults(self, tmp_path):
        h = ApiHarness(tmp_path)
        data = run(h.api.entries_post({"order": "2.5", "name": "缺省条目"}))
        entry = data["entry"]
        assert entry["order"] == 2.5
        assert entry["role"] == "system"
        assert entry["source"] == "text"
        assert entry["enabled"] is True

    def test_entries_post_invalid_role_rejected(self, tmp_path):
        with pytest.raises(ApiError) as ei:
            run(ApiHarness(tmp_path).api.entries_post({"order": 1, "name": "x", "role": "boss"}))
        assert ei.value.status_code == 400
        assert "role" in str(ei.value)

    def test_entries_post_non_dict_rejected(self, tmp_path):
        with pytest.raises(ApiError):
            run(ApiHarness(tmp_path).api.entries_post([{"order": 1, "name": "x"}]))

    def test_entries_post_duplicate_name_rejected(self, tmp_path):
        h = ApiHarness(tmp_path)
        add(h.api, name="重名")
        with pytest.raises(ApiError, match="已存在"):
            run(h.api.entries_post({"order": 2, "name": "重名"}))

    def test_entry_put_patches(self, tmp_path):
        h = ApiHarness(tmp_path)
        entry = add(h.api, name="旧名")
        data = run(h.api.entry_put(entry["id"], {"content": "新内容", "role": "assistant"}))
        assert data["entry"]["content"] == "新内容"
        assert data["entry"]["role"] == "assistant"
        assert data["entry"]["name"] == "旧名"

    def test_entry_put_unknown_id_404(self, tmp_path):
        with pytest.raises(ApiError) as ei:
            run(ApiHarness(tmp_path).api.entry_put("deadbeef", {"content": "x"}))
        assert ei.value.status_code == 404

    def test_entry_put_cannot_spoof_id(self, tmp_path):
        h = ApiHarness(tmp_path)
        entry = add(h.api)
        data = run(h.api.entry_put(entry["id"], {"id": "hack", "content": "x"}))
        assert data["entry"]["id"] == entry["id"]

    def test_entry_delete(self, tmp_path):
        h = ApiHarness(tmp_path)
        entry = add(h.api, name="要删的")
        data = run(h.api.entry_delete(entry["id"]))
        assert data["removed"] == "要删的"
        assert h.store.list_entries() == []

    def test_entry_delete_unknown_404(self, tmp_path):
        with pytest.raises(ApiError) as ei:
            run(ApiHarness(tmp_path).api.entry_delete("deadbeef"))
        assert ei.value.status_code == 404


class TestReorder:
    def test_reorder_rewrites_equal_spacing(self, tmp_path):
        h = ApiHarness(tmp_path)
        a = add(h.api, order=0, name="a")
        b = add(h.api, order=5, name="b")
        c = add(h.api, order=9, name="c")
        data = run(h.api.entries_reorder({"ids": [c["id"], a["id"], b["id"]]}))
        orders = {e["name"]: e["order"] for e in data["entries"]}
        assert orders == {"c": 0.0, "a": 10.0, "b": 20.0}

    def test_reorder_accepts_bare_list_and_persists(self, tmp_path):
        h = ApiHarness(tmp_path)
        a = add(h.api, name="a")
        b = add(h.api, name="b")
        run(h.api.entries_reorder([b["id"], a["id"]]))
        reloaded = EntryStore(h.store.path).list_entries()
        assert [e["name"] for e in reloaded] == ["b", "a"]
        assert [e["order"] for e in reloaded] == [0.0, 10.0]

    def test_reorder_validations(self, tmp_path):
        h = ApiHarness(tmp_path)
        a = add(h.api, name="a")
        b = add(h.api, name="b")
        with pytest.raises(ApiError, match="未知条目"):
            run(h.api.entries_reorder({"ids": ["deadbeef"]}))
        with pytest.raises(ApiError, match="重复"):
            run(h.api.entries_reorder({"ids": [a["id"], a["id"]]}))
        with pytest.raises(ApiError, match="缺少"):
            run(h.api.entries_reorder({"ids": [a["id"]]}))
        with pytest.raises(ApiError, match="id 列表"):
            run(h.api.entries_reorder({"ids": "不是列表"}))


class TestVariables:
    def test_variables_get(self, tmp_path):
        data = run(ApiHarness(tmp_path, variables={"user_name": "主人"}).api.variables_get())
        assert data == {"variables": {"user_name": "主人"}}

    def test_variables_put_updates_and_persists_via_setter(self, tmp_path):
        h = ApiHarness(tmp_path)
        data = run(h.api.variables_put({"bot_name": "凛", "user_name": "主人"}))
        assert data["variables"] == {"bot_name": "凛", "user_name": "主人"}
        assert h.saved_variables == [{"bot_name": "凛", "user_name": "主人"}]
        assert run(h.api.variables_get())["variables"]["bot_name"] == "凛"

    def test_variables_put_accepts_wrapper(self, tmp_path):
        h = ApiHarness(tmp_path)
        data = run(h.api.variables_put({"variables": {"k": "v"}}))
        assert data["variables"] == {"k": "v"}

    def test_variables_put_rejects_non_dict(self, tmp_path):
        with pytest.raises(ApiError, match="变量对象"):
            run(ApiHarness(tmp_path).api.variables_put(["不是字典"]))

    def test_variables_put_strips_keys(self, tmp_path):
        h = ApiHarness(tmp_path)
        data = run(h.api.variables_put({"  spaced  ": "v"}))
        assert data["variables"] == {"spaced": "v"}


class TestPreview:
    def test_preview_rows_use_var_context(self, tmp_path):
        h = ApiHarness(tmp_path)
        add(h.api, order=0, name="人格", source="persona")
        add(h.api, order=1, name="问候", content="你好，{{user_name}}")
        data = run(h.api.preview_get())
        assert data["count"] == 2
        assert data["persona_length"] == len(PERSONA)
        assert data["rows"][0]["snippet"] == PERSONA
        assert data["rows"][1]["snippet"] == "你好，主人"  # 变量已替换

    def test_preview_empty(self, tmp_path):
        data = run(ApiHarness(tmp_path).api.preview_get())
        assert data == {"rows": [], "count": 0, "persona_length": len(PERSONA)}


# ---------------------------------------------------------------------------
# main.py 适配层
# ---------------------------------------------------------------------------

class TestAdapter:
    def test_routes_registered_with_plugin_prefix(self, tmp_path):
        ctx = MockDashboardContext()
        make_plugin(tmp_path, context=ctx)
        pairs = {(route, tuple(methods)) for route, _, methods, _ in ctx.registered_routes}
        p = "/astrbot_plugin_prompt_preset"
        # 任务书需求 A 的 8 个端点（含动态段）全部注册（POST 别名供 Pages bridge 使用）
        assert (f"{p}/entries", ("GET", "POST")) in pairs
        assert (f"{p}/entries/reorder", ("PUT", "POST")) in pairs
        assert (f"{p}/entries/<item_id>", ("PUT", "POST")) in pairs
        assert (f"{p}/entries/<item_id>", ("DELETE",)) in pairs
        assert (f"{p}/entries/<item_id>/delete", ("POST",)) in pairs
        assert (f"{p}/variables", ("GET", "PUT", "POST")) in pairs
        assert (f"{p}/preview", ("GET",)) in pairs
        assert len(ctx.registered_routes) == 7
        # 全部 handler 带描述
        assert all(desc for _, _, _, desc in ctx.registered_routes)

    def test_adapter_post_branch_creates_entry(self, tmp_path, monkeypatch):
        import astrbot_plugin_prompt_preset.main as plugin_main

        plugin = make_plugin(tmp_path)
        monkeypatch.setattr(
            plugin_main, "_api_request", FakeApiRequest("POST", {"order": 1, "name": "面板加的"})
        )
        result = run(plugin._api_entries())
        assert result["status"] == "ok"
        assert result["data"]["entry"]["name"] == "面板加的"
        assert plugin.store.get("面板加的")

    def test_adapter_converts_api_error(self, tmp_path, monkeypatch):
        import astrbot_plugin_prompt_preset.main as plugin_main

        plugin = make_plugin(tmp_path)
        monkeypatch.setattr(
            plugin_main, "_api_request", FakeApiRequest("POST", {"order": 1, "role": "boss", "name": "x"})
        )
        result = run(plugin._api_entries())
        assert result["status"] == "error"
        assert result["status_code"] == 400
        assert "role" in result["message"]

    def test_adapter_get_branch(self, tmp_path, monkeypatch):
        import astrbot_plugin_prompt_preset.main as plugin_main

        plugin = make_plugin(tmp_path)
        plugin.store.add({"order": 0, "name": "已有"})
        monkeypatch.setattr(plugin_main, "_api_request", FakeApiRequest("GET"))
        result = run(plugin._api_entries())
        assert [e["name"] for e in result["data"]["entries"]] == ["已有"]


# ---------------------------------------------------------------------------
# HTTP 层：FastAPI TestClient（与 main.py 注册表同构的挂载）
# ---------------------------------------------------------------------------

def build_fastapi_app(api: PromptPresetAPI):
    """把 PromptPresetAPI 挂到真实 HTTP 框架上（与 main.py 的路由表同构）。"""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI()
    prefix = "/api/prompt_preset"

    def ok(data):
        return JSONResponse(data)

    def fail(e: ApiError):
        return JSONResponse({"status": "error", "message": str(e)}, status_code=e.status_code)

    @app.get(prefix + "/entries")
    async def entries_get():
        try:
            return ok(await api.entries_get())
        except ApiError as e:
            return fail(e)

    @app.post(prefix + "/entries")
    async def entries_post(request: Request):
        try:
            return ok(await api.entries_post(await request.json()))
        except ApiError as e:
            return fail(e)

    # 注意顺序：静态段 reorder 必须先于动态段 {item_id} 注册
    @app.put(prefix + "/entries/reorder")
    async def entries_reorder(request: Request):
        try:
            return ok(await api.entries_reorder(await request.json()))
        except ApiError as e:
            return fail(e)

    @app.put(prefix + "/entries/{item_id}")
    async def entry_put(item_id: str, request: Request):
        try:
            return ok(await api.entry_put(item_id, await request.json()))
        except ApiError as e:
            return fail(e)

    @app.delete(prefix + "/entries/{item_id}")
    async def entry_delete(item_id: str):
        try:
            return ok(await api.entry_delete(item_id))
        except ApiError as e:
            return fail(e)

    @app.get(prefix + "/variables")
    async def variables_get():
        try:
            return ok(await api.variables_get())
        except ApiError as e:
            return fail(e)

    @app.put(prefix + "/variables")
    async def variables_put(request: Request):
        try:
            return ok(await api.variables_put(await request.json()))
        except ApiError as e:
            return fail(e)

    @app.get(prefix + "/preview")
    async def preview_get():
        try:
            return ok(await api.preview_get())
        except ApiError as e:
            return fail(e)

    return app


@pytest.fixture
def http_client(tmp_path):
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    harness = ApiHarness(tmp_path)
    client = TestClient(build_fastapi_app(harness.api))
    return harness, client


class TestHTTP:
    def test_entries_crud_over_http(self, http_client):
        harness, client = http_client
        # POST 创建
        resp = client.post(
            "/api/prompt_preset/entries",
            json={"order": 1, "role": "system", "name": "HTTP 条目", "content": "正文"},
        )
        assert resp.status_code == 200
        entry_id = resp.json()["entry"]["id"]
        # GET 列表
        resp = client.get("/api/prompt_preset/entries")
        assert [e["name"] for e in resp.json()["entries"]] == ["HTTP 条目"]
        # PUT 更新
        resp = client.put(f"/api/prompt_preset/entries/{entry_id}", json={"content": "改了"})
        assert resp.json()["entry"]["content"] == "改了"
        # DELETE 删除
        resp = client.delete(f"/api/prompt_preset/entries/{entry_id}")
        assert resp.json()["removed"] == "HTTP 条目"
        assert client.get("/api/prompt_preset/entries").json()["entries"] == []

    def test_reorder_and_preview_over_http(self, http_client):
        harness, client = http_client
        ids = []
        for name in ("甲", "乙", "丙"):
            ids.append(
                client.post(
                    "/api/prompt_preset/entries",
                    json={"order": 0, "name": name, "content": f"{name}的内容"},
                ).json()["entry"]["id"]
            )
        resp = client.put("/api/prompt_preset/entries/reorder", json={"ids": ids[::-1]})
        assert [e["name"] for e in resp.json()["entries"]] == ["丙", "乙", "甲"]
        assert [e["order"] for e in resp.json()["entries"]] == [0.0, 10.0, 20.0]

        resp = client.get("/api/prompt_preset/preview")
        body = resp.json()
        assert body["count"] == 3
        assert body["rows"][0]["snippet"] == "丙的内容"

    def test_http_error_shape(self, http_client):
        _, client = http_client
        resp = client.post("/api/prompt_preset/entries", json={"order": 1, "role": "boss", "name": "x"})
        assert resp.status_code == 400
        body = resp.json()
        assert body["status"] == "error" and "role" in body["message"]

        resp = client.put("/api/prompt_preset/entries/deadbeef", json={"content": "x"})
        assert resp.status_code == 404

        resp = client.put("/api/prompt_preset/entries/reorder", json={"ids": ["deadbeef"]})
        assert resp.status_code == 400

    def test_variables_over_http(self, http_client):
        _, client = http_client
        resp = client.get("/api/prompt_preset/variables")
        assert resp.json()["variables"]["user_name"] == "主人"
        resp = client.put("/api/prompt_preset/variables", json={"user_name": "水煮冰糕"})
        assert resp.json()["variables"] == {"user_name": "水煮冰糕"}
