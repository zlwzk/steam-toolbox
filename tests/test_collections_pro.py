"""完整版激活态与库自动分类引擎测试。无网络、无真实凭证、不写 Steam 文件。"""
import pytest
from fastapi.testclient import TestClient

from backend import collections_engine as engine, config, database
from backend.collections_data import MANUAL
from backend.main import app
from backend.settings_validation import EDITABLE_KEYS

client = TestClient(app, base_url="http://127.0.0.1:8000")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "pro.db")
    database.init_db()
    yield


def _game(appid=1, **over):
    base = {
        "appid": appid, "name": "Sample", "type": "game", "yr": 2018, "cn": None,
        "tags": ["动作"], "dev": [], "cat": [1], "jp": 0, "en": 1, "nlang": 3, "inlib": True,
    }
    base.update(over)
    return base


# ---------- 引擎分类规则 ----------

def test_visual_novel_locks_category_seven():
    g = _game(100, tags=["视觉小说", "恋爱"])
    plan = engine.classify([g], 5, {})
    assert plan and plan[0]["c"] == 7


def test_old_game_falls_back_to_retro_category():
    g = _game(101, yr=2005, tags=["动作"])
    plan = engine.classify([g], 5, {})
    assert plan and plan[0]["c"] == 24


def test_manual_overrides_primary_category():
    appid, cat = next(iter(MANUAL.items()))
    g = _game(appid, tags=["射击"])
    plan = engine.classify([g], 5, {})
    if cat == 0:
        # 0 表示该游戏不参与分类，不应出现在方案里
        assert not plan
    else:
        assert plan and plan[0]["c"] == cat


def test_empty_overrides_excludes_game():
    g = _game(102, tags=["动作"])
    plan = engine.classify([g], 5, {str(102): []})
    assert plan == []


def test_memberships_keep_valid_category_ids():
    g = _game(103, tags=["动作", "冒险"])
    plan = engine.classify([g], 5, {})
    assert plan
    assert plan[0]["all"] and plan[0]["c"] == plan[0]["all"][0]


# ---------- Pro 激活态与路由门禁 ----------

def test_pro_defaults_locked_then_unlocks(isolated_db):
    r = client.get("/api/pro/status")
    assert r.status_code == 200
    assert r.json()["unlocked"] is False

    r = client.post("/api/pro/unlock")
    assert r.status_code == 200
    assert r.json()["unlocked"] is True

    r = client.get("/api/pro/status")
    assert r.json()["unlocked"] is True


def test_collections_route_gated_before_unlock(isolated_db):
    r = client.get("/api/collections/status")
    assert r.status_code == 403


def test_collections_status_open_after_unlock(isolated_db):
    client.post("/api/pro/unlock")
    r = client.get("/api/collections/status")
    assert r.status_code == 200
    body = r.json()
    assert "accounts" in body and "running" in body


def test_pro_key_not_exposed_to_settings_page():
    assert "pro_unlocked" not in EDITABLE_KEYS
