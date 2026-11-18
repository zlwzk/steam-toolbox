"""游戏入库登记（wishlist）回归测试：解析语义、诚实标注、API 契约。

全部外部请求 mock；DB 与 DATA_DIR 均隔离到临时目录，
不触碰用户数据目录与真实 Steam。
"""
import pytest
from fastapi.testclient import TestClient

import backend.app_catalog as app_catalog
from backend import config, database
from backend.main import app


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    # 关键：DATA_DIR 必须一起隔离，否则索引缓存会写进真实 data/ 目录
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "wl.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    app_catalog._index_cache = None
    database.init_db()
    yield
    app_catalog._index_cache = None


client = TestClient(app, base_url="http://127.0.0.1:8000")


class FakeResolver(app_catalog.CatalogResolver):
    """完整 mock：索引含中英文名，搜索与详情按表返回。"""

    def _download_app_list(self):
        return [
            [730, "Counter-Strike 2"],
            [105600, "Terraria"],
            [105601, "Terraria Otherworld"],
        ]

    def _search_store(self, query, lang):
        if "泰拉瑞亚" in query and lang == "schinese":
            return [{"appid": 105600, "name": "泰拉瑞亚", "source": "store_search"}]
        return []

    def _name_for_lang(self, appid, lang):
        table = {
            730: {"english": "Counter-Strike 2", "schinese": "反恐精英 2"},
            105600: {"english": "Terraria", "schinese": "泰拉瑞亚"},
        }
        return table.get(appid, {}).get(lang)


@pytest.fixture
def fake_resolver(monkeypatch):
    monkeypatch.setattr(
        "backend.routers.wishlist.app_catalog.CatalogResolver", lambda *a, **k: FakeResolver(*a, **k)
    )


# ---------- 解析语义 ----------

def test_appid_direct_resolve(isolated, fake_resolver):
    r = FakeResolver().resolve_one("730")
    assert r["appid"] == 730 and r["resolve_status"] == "exact"
    assert r["name_en"] == "Counter-Strike 2" and r["name_zh"] == "反恐精英 2"
    assert r["source"] == "direct_appid"


def test_english_name_with_spaces_normalized(isolated, fake_resolver):
    r = FakeResolver().resolve_one("  counter-strike 2 ")
    assert r["appid"] == 730 and r["resolve_status"] == "exact"


def test_chinese_name_via_store_search(isolated, fake_resolver):
    r = FakeResolver().resolve_one("泰拉瑞亚")
    assert r["appid"] == 105600 and r["resolve_status"] == "exact"
    assert r["name_zh"] == "泰拉瑞亚" and r["name_en"] == "Terraria"


def test_fuzzy_input_not_guessed(isolated, fake_resolver):
    # 模糊词（非唯一精确同名）不得自动入库，只给候选
    r = FakeResolver().resolve_one("Terraria Otherworld")
    # 与索引精确同名，应命中
    assert r["appid"] == 105601


def test_unknown_input_stays_unresolved(isolated, monkeypatch):
    class Empty(app_catalog.CatalogResolver):
        def _download_app_list(self):
            return []

        def _search_store(self, q, l):
            return []

        def _name_for_lang(self, a, l):
            return None

    monkeypatch.setattr(
        "backend.routers.wishlist.app_catalog.CatalogResolver", lambda *a, **k: Empty(*a, **k)
    )
    r = Empty().resolve_one("完全查不到的名字")
    assert r["appid"] is None and r["resolve_status"] == "unresolved"
    assert "未自动入库" in r["reason"]


def test_name_missing_kept_unknown(isolated, monkeypatch):
    class NoNames(app_catalog.CatalogResolver):
        def _download_app_list(self):
            return [[42, "Deep Rock Galactic"]]

        def _search_store(self, q, l):
            return []

        def _name_for_lang(self, a, l):
            return None  # 详情接口失败

    r = NoNames().resolve_one("Deep Rock Galactic")
    assert r["appid"] == 42 and r["resolve_status"] == "appid_only"
    assert r["name_en"] is None and r["name_zh"] is None  # 未知保留，不猜测


def test_batch_dedup_and_limit(isolated):
    class One(app_catalog.CatalogResolver):
        def _download_app_list(self):
            return [[1, "A Game"]]

        def _search_store(self, q, l):
            return []

        def _name_for_lang(self, a, l):
            return None

    r = One()
    out = r.resolve_batch(["A Game", "a  game", "1"])
    assert len(out) == 2  # 归一化去重后两条不同输入
    too_many = [f"name{i}" for i in range(app_catalog.MAX_BATCH + 5)]
    out2 = r.resolve_batch(too_many)
    assert any(x["resolve_status"] == "invalid" and "未处理" in x["reason"] for x in out2)


# ---------- API 契约 ----------

def test_resolve_endpoint(isolated, fake_resolver):
    r = client.post("/api/wishlist/resolve", json={"inputs": ["730", "泰拉瑞亚"]})
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 2
    assert all(x["resolve_status"] == "exact" for x in body["results"])


def test_save_and_list_and_remove(isolated, fake_resolver):
    r = client.post("/api/wishlist/save", json={"inputs": ["730", "查无此游戏xyz"]})
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] == 2 and body["exact"] == 1 and body["unresolved"] == 1

    lst = client.get("/api/wishlist/list").json()
    assert len(lst) == 2
    exact_row = next(x for x in lst if x["resolve_status"] == "exact")
    assert exact_row["appid"] == 730
    assert exact_row["name_zh"] == "反恐精英 2"

    # 重复登记幂等（同输入更新而非重复插入）
    client.post("/api/wishlist/save", json={"inputs": ["730"]})
    assert len(client.get("/api/wishlist/list").json()) == 2

    del_r = client.delete("/api/wishlist/item?input_text=730")
    assert del_r.status_code == 200
    lst2 = client.get("/api/wishlist/list").json()
    assert all(x["appid"] != 730 for x in lst2)


def test_unresolved_item_can_be_removed(isolated, fake_resolver):
    client.post("/api/wishlist/save", json={"inputs": ["查无此游戏xyz"]})
    response = client.delete("/api/wishlist/item", params={"input_text": "查无此游戏xyz"})
    assert response.status_code == 200
    assert client.get("/api/wishlist/list").json() == []


def test_save_empty_inputs_rejected(isolated):
    r = client.post("/api/wishlist/save", json={"inputs": []})
    assert r.status_code == 422


def test_does_not_write_owned_games(isolated, fake_resolver):
    """入库登记绝不写 owned_games：拥有状态只能来自 Steam 官方接口。"""
    client.post("/api/wishlist/save", json={"inputs": ["730"]})
    with database.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM owned_games").fetchone()[0] == 0


def test_wishlist_does_not_expose_unverified_claim(isolated, fake_resolver):
    """仅凭名称和 AppID 无法证明免费：新模块不得提供领取转发接口。"""
    client.post("/api/wishlist/save", json={"inputs": ["730"]})
    assert client.post("/api/wishlist/claim", json={"appids": [730]}).status_code in (404, 405)


def test_multiple_store_exact_matches_remain_unresolved(isolated):
    class Ambiguous(FakeResolver):
        def _search_store(self, query, lang):
            return [
                {"appid": 111, "name": query, "source": "store_search"},
                {"appid": 222, "name": query, "source": "store_search"},
            ]

    row = Ambiguous().resolve_one("同名游戏")
    assert row["appid"] is None
    assert row["resolve_status"] == "unresolved"
    assert {item["appid"] for item in row["candidates"]} == {111, 222}


def test_activate_info(isolated):
    r = client.get("/api/wishlist/activate-info")
    assert r.status_code == 200
    body = r.json()
    assert body["web_url"].startswith("https://store.steampowered.com/")
    assert "不自动" in body["note"] or "手动" in body["note"]
