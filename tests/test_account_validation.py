"""账号绑定：SteamID 校验规则统一；测试连接不修改已保存设置。全部使用 mock，无真实网络。"""
import pytest
from fastapi.testclient import TestClient

from backend import config, database
from backend.main import app

client = TestClient(app, base_url="http://127.0.0.1:8000")

VALID_ID = "76561190000000000"   # 17 位
SHORT_ID = "7656119000000000"    # 16 位
LONG_ID = "765611900000000000"   # 18 位


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "account.db")
    database.init_db()
    yield


class _FakeClient:
    """只读假客户端：不发起任何网络请求。"""

    last_instance = None

    def __init__(self, api_key="", steamid="", cc=None, lang=None, verify_ssl=True):
        self.api_key = api_key
        self.steamid = steamid
        self.cc = cc
        self.lang = lang
        type(self).last_instance = self

    def get_country_code(self):
        return "us"

    def get_owned_games(self):
        return [{"appid": 730}, {"appid": 440}]


@pytest.fixture
def fake_client(monkeypatch):
    import backend.routers.account as account_router
    monkeypatch.setattr(account_router, "SteamClient", _FakeClient)
    return _FakeClient


# ---------- SteamID 校验：前后端同一语义（17 位纯数字） ----------

@pytest.mark.parametrize("sid,valid", [
    (VALID_ID, True),
    (SHORT_ID, False),
    (LONG_ID, False),
    ("7656119abcdefgh", False),
    ("", True),  # 留空表示不修改已保存值
])
def test_save_account_steamid_rule(isolated_db, fake_client, sid, valid):
    r = client.post("/api/account", json={"steamid": sid})
    assert r.status_code == 200
    body = r.json()
    if valid:
        assert body["ok"] is True
    else:
        assert body["ok"] is False
        assert "17 位纯数字" in body["error"]


def test_save_account_rejects_wrong_length_even_with_key(isolated_db, fake_client):
    r = client.post("/api/account", json={"api_key": "k", "steamid": LONG_ID})
    assert r.json()["ok"] is False


# ---------- 测试连接：只读，不落库 ----------

def test_test_account_does_not_persist_settings(isolated_db, fake_client):
    # 预置已保存设置
    database.update_settings({"api_key": "saved-key", "steamid": VALID_ID,
                              "cc": "cn", "lang": "schinese"})
    r = client.post("/api/account/test", json={"api_key": "other-key", "steamid": VALID_ID,
                                               "lang": "english"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["owned_count"] == 2
    assert body["cc"] == "us"          # 识别结果随响应返回
    assert body["cc_detected"] is True

    saved = database.get_settings()
    assert saved["cc"] == "cn", "测试连接不得改写已保存商店区"
    assert saved["lang"] == "schinese", "测试连接不得改写已保存语言"
    assert saved["api_key"] == "saved-key", "测试连接不得改写已保存 Key"


def test_test_account_failure_returns_error(isolated_db, monkeypatch):
    import backend.routers.account as account_router
    from backend.steam_client import SteamApiError

    class _FailClient(_FakeClient):
        def get_owned_games(self):
            raise SteamApiError("API Key 无效或已失效，请重新到 Steam 申请 Key 后保存", 401)

    monkeypatch.setattr(account_router, "SteamClient", _FailClient)
    database.update_settings({"api_key": "bad", "steamid": VALID_ID})
    r = client.post("/api/account/test", json={})
    assert r.json()["ok"] is False
    assert "API Key" in r.json()["error"]


def test_save_account_persists_on_save(isolated_db, fake_client):
    r = client.post("/api/account", json={"api_key": "new-key", "steamid": VALID_ID,
                                          "lang": "english"})
    assert r.json()["ok"] is True
    saved = database.get_settings()
    assert saved["api_key"] == "new-key"
    assert saved["steamid"] == VALID_ID
    assert saved["lang"] == "english"
    assert saved["cc"] == "us"  # 保存时允许识别并写入
