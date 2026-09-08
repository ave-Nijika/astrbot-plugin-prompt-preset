"""条目持久化测试：CRUD 全流程 + JSON 落盘。"""

import json

import pytest

from astrbot_plugin_prompt_preset.core.entry_store import (
    EntryStore,
    EntryValidationError,
    VALID_ROLES,
    VALID_SOURCES,
)
from tests.helpers import make_store

ENTRY = {
    "order": 1,
    "role": "system",
    "source": "text",
    "content": "你好",
    "enabled": True,
    "name": "条目一",
}


class TestAdd:
    def test_add_and_list(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        entries = store.list_entries()
        assert len(entries) == 1
        assert entries[0]["name"] == "条目一"
        assert entries[0]["order"] == 1.0  # int → float 规范化
        assert entries[0]["id"]  # store 生成了管理 id

    def test_add_defaults(self, tmp_path):
        entry = make_store(tmp_path, [{"order": "2.5", "name": "只有名字"}]).list_entries()[0]
        assert entry["order"] == 2.5  # 数字字符串被转换
        assert entry["role"] == "system"
        assert entry["source"] == "text"
        assert entry["content"] == ""
        assert entry["enabled"] is True

    def test_add_persists_to_json(self, tmp_path):
        make_store(tmp_path, [ENTRY])
        raw = json.loads((tmp_path / "presets.json").read_text(encoding="utf-8"))
        assert raw[0]["name"] == "条目一"

    def test_add_duplicate_name_rejected(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        with pytest.raises(EntryValidationError, match="已存在"):
            store.add({**ENTRY, "order": 99})

    def test_add_missing_order_rejected(self, tmp_path):
        with pytest.raises(EntryValidationError, match="order"):
            make_store(tmp_path, [{"name": "无排序"}])

    def test_add_bad_order_rejected(self, tmp_path):
        with pytest.raises(EntryValidationError, match="order"):
            make_store(tmp_path, [{"order": "abc", "name": "x"}])

    def test_add_infinite_order_rejected(self, tmp_path):
        with pytest.raises(EntryValidationError, match="order"):
            make_store(tmp_path, [{"order": float("inf"), "name": "x"}])

    def test_add_bad_role_rejected(self, tmp_path):
        with pytest.raises(EntryValidationError, match="role"):
            make_store(tmp_path, [{"order": 1, "role": "tool", "name": "x"}])

    def test_add_bad_source_rejected(self, tmp_path):
        with pytest.raises(EntryValidationError, match="source"):
            make_store(tmp_path, [{"order": 1, "source": "memory", "name": "x"}])

    def test_add_empty_name_rejected(self, tmp_path):
        with pytest.raises(EntryValidationError):
            make_store(tmp_path, [{"order": 1}])

    def test_role_source_values(self):
        assert VALID_ROLES == ("system", "user", "assistant")
        assert VALID_SOURCES == ("text", "persona", "chat_history")


class TestGetRemove:
    def test_get_by_name(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        assert store.get("条目一")["content"] == "你好"

    def test_get_by_id(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        eid = store.list_entries()[0]["id"]
        assert store.get(eid)["name"] == "条目一"

    def test_get_missing_returns_none(self, tmp_path):
        assert make_store(tmp_path, [ENTRY]).get("不存在") is None

    def test_remove_by_name(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        removed = store.remove("条目一")
        assert removed["name"] == "条目一"
        assert store.list_entries() == []

    def test_remove_persists(self, tmp_path):
        store = make_store(tmp_path, [ENTRY, {**ENTRY, "name": "条目二"}])
        store.remove("条目一")
        assert [e["name"] for e in EntryStore(tmp_path / "presets.json").list_entries()] == ["条目二"]

    def test_remove_missing_returns_none(self, tmp_path):
        assert make_store(tmp_path, [ENTRY]).remove("不存在") is None


class TestUpdateReorderToggle:
    def test_update_patch(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        updated = store.update("条目一", {"content": "改了", "role": "user"})
        assert updated["content"] == "改了"
        assert updated["role"] == "user"
        assert updated["order"] == 1.0  # 未触碰的字段保持

    def test_update_persists(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        store.update("条目一", {"content": "改了"})
        assert EntryStore(tmp_path / "presets.json").get("条目一")["content"] == "改了"

    def test_update_missing_returns_none(self, tmp_path):
        assert make_store(tmp_path, [ENTRY]).update("不存在", {"content": "x"}) is None

    def test_update_invalid_value_rejected(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        with pytest.raises(EntryValidationError):
            store.update("条目一", {"role": "boss"})

    def test_update_id_immutable(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        old_id = store.get("条目一")["id"]
        updated = store.update("条目一", {"id": "hack", "content": "x"})
        assert updated["id"] == old_id

    def test_update_renamed_duplicate_rejected(self, tmp_path):
        store = make_store(tmp_path, [ENTRY, {**ENTRY, "name": "条目二"}])
        with pytest.raises(EntryValidationError, match="已存在"):
            store.update("条目二", {"name": "条目一"})

    def test_reorder(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        assert store.reorder("条目一", "3.5")["order"] == 3.5

    def test_reorder_missing_returns_none(self, tmp_path):
        assert make_store(tmp_path, [ENTRY]).reorder("不存在", 2) is None

    def test_toggle_flip(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        assert store.toggle("条目一")["enabled"] is False
        assert store.toggle("条目一")["enabled"] is True

    def test_toggle_set_explicit(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        assert store.toggle("条目一", False)["enabled"] is False
        assert store.toggle("条目一", False)["enabled"] is False

    def test_toggle_missing_returns_none(self, tmp_path):
        assert make_store(tmp_path, [ENTRY]).toggle("不存在") is None


class TestPersistence:
    def test_list_sorted_by_order(self, tmp_path):
        store = make_store(
            tmp_path,
            [{"order": 10, "name": "b"}, {"order": -1, "name": "a"}, {"order": 2, "name": "c"}],
        )
        assert [e["name"] for e in store.list_entries()] == ["a", "c", "b"]

    def test_list_returns_copies(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        entries = store.list_entries()
        entries[0]["name"] = "篡改"
        assert store.list_entries()[0]["name"] == "条目一"

    def test_load_missing_file_empty(self, tmp_path):
        assert EntryStore(tmp_path / "none.json").list_entries() == []

    def test_load_coerces_and_sorts(self, tmp_path):
        path = tmp_path / "presets.json"
        path.write_text(
            json.dumps(
                [{"order": 5, "name": "大", "role": "assistant"},
                 {"name": "缺省", "order": 1}],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        entries = EntryStore(path).list_entries()
        assert [e["name"] for e in entries] == ["缺省", "大"]
        assert entries[1]["role"] == "assistant"
        assert entries[0]["source"] == "text"

    def test_load_skips_invalid_entries(self, tmp_path):
        path = tmp_path / "presets.json"
        path.write_text(
            json.dumps(
                [{"order": 1, "name": "好的"}, {"order": "oops", "name": "坏的"}],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        entries = EntryStore(path).list_entries()
        assert [e["name"] for e in entries] == ["好的"]

    def test_load_corrupt_json_backed_up(self, tmp_path):
        path = tmp_path / "presets.json"
        path.write_text("{不是 JSON", encoding="utf-8")
        store = EntryStore(path)
        assert store.list_entries() == []
        assert (tmp_path / "presets.json.bak").read_text(encoding="utf-8") == "{不是 JSON"
        # 且 store 可继续正常使用
        store.add({"order": 1, "name": "重新开始"})
        assert len(store.list_entries()) == 1

    def test_save_leaves_no_tmp_file(self, tmp_path):
        store = make_store(tmp_path, [ENTRY])
        store.add({"order": 2, "name": "第二条"})
        assert sorted(p.name for p in tmp_path.iterdir()) == ["presets.json"]
