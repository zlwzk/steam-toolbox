"""付费 DLC 默认从候选清单与汇总中剔除的回归测试（本地临时库，无网络）。"""
import pytest
from fastapi.testclient import TestClient

from backend import config, database
from backend.main import app

client = TestClient(app, base_url="http://127.0.0.1:8000")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    database.init_db()
    yield


def _seed():
    items = [
        (1001, "claimable", "免费 DLC，可领取", 0),
        (2001, "skipped", "付费 DLC（CNY 2200）", 2200),
        (2002, "skipped", "本体未拥有", None),
        (3001, "unknown", "无价格信息，需人工确认是否免费", None),
    ]
    with database.get_conn() as conn:
        for appid, status, reason, price in items:
            conn.execute(
                "INSERT INTO dlc_items(dlc_appid, parent_appid, name, type, price_initial, price_final, currency) "
                "VALUES (?, 1, ?, 'dlc', ?, ?, 'CNY')",
                (appid, f"dlc-{appid}", price, price),
            )
            conn.execute(
                "INSERT INTO candidates(dlc_appid, item_type, status, reason, added_at, updated_at) "
                "VALUES (?, 'dlc', ?, ?, 't', 't')",
                (appid, status, reason),
            )


def test_paid_dlc_hidden_by_default(isolated_db):
    _seed()
    rows = client.get("/api/candidates").json()
    appids = {r["dlc_appid"] for r in rows}
    assert 2001 not in appids
    assert {1001, 2002, 3001} <= appids

    skipped = client.get("/api/candidates?status=skipped").json()
    assert {r["dlc_appid"] for r in skipped} == {2002}

    paid_rows = client.get("/api/candidates?include_paid=true").json()
    assert 2001 in {r["dlc_appid"] for r in paid_rows}


def test_summary_splits_paid_from_skipped(isolated_db):
    _seed()
    summ = client.get("/api/candidates/summary?item_type=dlc").json()
    assert summ["claimable"] == 1
    assert summ["skipped"] == 1
    assert summ["unknown"] == 1
    assert summ["paid"] == 1
    assert summ["total"] == 3
