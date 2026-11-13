"""更新监控模块测试：校验、规则匹配、指纹、CRUD 与路由。无网络与真实凭证。"""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import claimer, config, database, monitor
from backend.main import app

client = TestClient(app, base_url="http://127.0.0.1:8000")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "monitor.db")
    database.init_db()
    yield


# ---------- 输入校验 ----------

def test_valid_appid_rejects_bad_input():
    with pytest.raises(HTTPException):
        monitor._valid_appid("abc")
    with pytest.raises(HTTPException):
        monitor._valid_appid("0")
    with pytest.raises(HTTPException):
        monitor._valid_appid("-10")
    assert monitor._valid_appid("730") == 730


def test_valid_file_id_rejects_bad_input():
    with pytest.raises(HTTPException):
        monitor._valid_file_id("")
    with pytest.raises(HTTPException):
        monitor._valid_file_id("12.5")
    assert monitor._valid_file_id("123456789") == 123456789


def test_normalize_keywords_dedup_and_split():
    out = monitor._normalize_keywords("Chinese, 汉化 ,chinese, 中文")
    assert out == "chinese,汉化,中文"
    with pytest.raises(HTTPException):
        monitor._normalize_keywords("   ")


# ---------- 规则匹配 ----------

def test_rule_match_any():
    rule = {"enabled": 1, "appid": 0, "keywords": "汉化,中文", "match_mode": "any"}
    assert monitor._rule_matches(rule, "Chinese Mod", ["translation"], 730) == []
    assert set(monitor._rule_matches(rule, "中文汉化包", [], 730)) == {"中文", "汉化"}


def test_rule_match_all_requires_every_keyword():
    rule = {"enabled": 1, "appid": 0, "keywords": "chinese,map", "match_mode": "all"}
    assert monitor._rule_matches(rule, "chinese map pack", [], 730) == ["chinese", "map"]
    assert monitor._rule_matches(rule, "chinese only", [], 730) == []


def test_rule_respects_appid_and_enabled():
    rule = {"enabled": 1, "appid": 440, "keywords": "bot", "match_mode": "any"}
    assert monitor._rule_matches(rule, "bot pack", [], 730) == []
    assert monitor._rule_matches(rule, "bot pack", [], 440) == ["bot"]
    disabled = {**rule, "enabled": 0}
    assert monitor._rule_matches(disabled, "bot pack", [], 440) == []


# ---------- 指纹 ----------

def test_store_fingerprint_detects_change():
    body = {"name": "Game", "type": "game", "price_overview": {"final": 0},
            "dlc": [1, 2], "release_date": {"date": "2020-01-01"},
            "header_image": "a.jpg", "supported_languages": "en,zh"}
    fp1 = monitor._store_fingerprint(body)
    body2 = {**body, "price_overview": {"final": 500}}
    fp2 = monitor._store_fingerprint(body2)
    assert fp1 and fp2 and fp1 != fp2
    assert monitor._store_fingerprint(None) is None


# ---------- 路由与 CRUD ----------

def test_game_mod_rule_crud_over_http(isolated_db):
    r = client.post("/api/monitor/games", json={"appid": "730", "watch_store": True, "watch_workshop": True})
    assert r.status_code == 200 and r.json()["ok"]
    games = client.get("/api/monitor/games").json()
    assert len(games) == 1 and games[0]["appid"] == 730

    r = client.post("/api/monitor/mods", json={"file_id": "123456", "appid": "730"})
    assert r.status_code == 200 and r.json()["ok"]
    mods = client.get("/api/monitor/mods").json()
    assert mods[0]["published_file_id"] == 123456

    r = client.post("/api/monitor/rules", json={"appid": "730", "keywords": "汉化,中文",
                                                "match_mode": "any", "auto_subscribe": True,
                                                "enabled": True, "note": "测试"})
    assert r.status_code == 200 and r.json()["ok"]
    rules = client.get("/api/monitor/rules").json()
    assert len(rules) == 1 and rules[0]["auto_subscribe"] == 1

    rid = rules[0]["id"]
    r = client.put(f"/api/monitor/rules/{rid}", json={"appid": "0", "keywords": "english",
                                                       "match_mode": "all", "auto_subscribe": False,
                                                       "enabled": False, "note": ""})
    assert r.json()["ok"]
    assert client.get("/api/monitor/rules").json()[0]["keywords"] == "english"

    client.delete(f"/api/monitor/rules/{rid}")
    client.delete("/api/monitor/mods/123456")
    client.delete("/api/monitor/games/730")
    assert client.get("/api/monitor/games").json() == []


def test_events_add_and_mark_read(isolated_db):
    eid = database.add_watch_event("mod_new", 730, 111, "Test Mod", "新上架")
    events = client.get("/api/monitor/events").json()
    assert len(events) == 1 and events[0]["seen"] == 0
    r = client.post("/api/monitor/events/read", json={"ids": []})
    assert r.json()["marked"] == 1
    assert client.get("/api/monitor/events", params={"unread": True}).json() == []
    assert eid > 0


def test_settings_validation_bounds(isolated_db):
    r = client.put("/api/monitor/settings", json={"watch_interval_minutes": 5})
    assert r.status_code == 400
    r = client.put("/api/monitor/settings", json={"watch_workshop_top": 99})
    assert r.status_code == 400
    r = client.put("/api/monitor/settings", json={"watch_auto": True, "watch_interval_minutes": 60,
                                                  "watch_auto_subscribe": False, "watch_workshop_top": 10})
    assert r.status_code == 200 and r.json()["ok"]
    s = client.get("/api/monitor/settings").json()
    assert s["watch_auto"] is True and s["watch_interval_minutes"] == 60
    assert s["watch_workshop_top"] == 10


def test_overview_and_progress_endpoints(isolated_db):
    ov = client.get("/api/monitor/overview").json()
    assert ov["watch_games"] == 0 and ov["watch_unread"] == 0
    prog = client.get("/api/monitor/progress").json()
    assert prog["state"] in ("idle", "running", "done", "error", "blocked")


def test_add_game_rejects_bad_appid(isolated_db):
    r = client.post("/api/monitor/games", json={"appid": "not-a-number"})
    assert r.status_code == 400


def test_login_status_initial_idle():
    status = claimer.get_login_status()
    assert status["state"] in ("idle", "starting", "ready", "logged_in", "closed", "blocked", "error")


class _FakeWorkshopClient:
    """只读假客户端：返回预置工坊列表，不发起真实网络请求。"""

    def __init__(self, items):
        self._items = items

    def query_workshop(self, appid, num_per_page=20, cursor=None):
        return {"items": self._items}


def test_workshop_first_run_baseline_records_no_events(isolated_db):
    database.upsert_watch_game(730, name="CS2")
    items = [
        {"file_id": 111, "time_updated": 1000, "title": "Mod A", "tags": ["map"]},
        {"file_id": 222, "time_updated": 2000, "title": "Mod B", "tags": []},
    ]
    events = monitor._detect_workshop(_FakeWorkshopClient(items), database.get_watch_game(730))
    # 首次建档只存基线，不把首屏 Mod 误报为新上架
    assert events == []
    snap = database.get_watch_game(730)
    assert snap["last_workshop_top"]

    # 第二次检测：出现一个新 Mod、一个有更新的旧 Mod
    items2 = [
        {"file_id": 111, "time_updated": 1500, "title": "Mod A", "tags": ["map"]},
        {"file_id": 222, "time_updated": 2000, "title": "Mod B", "tags": []},
        {"file_id": 333, "time_updated": 3000, "title": "Mod C", "tags": []},
    ]
    events2 = monitor._detect_workshop(_FakeWorkshopClient(items2), database.get_watch_game(730))
    kinds = {e["kind"] for e in events2}
    assert "mod_new" in kinds
    assert "mod_update" in kinds

