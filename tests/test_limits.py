"""列表接口 limit 防护：API 层拒绝非正数/越界，数据层兜底归一化。"""
import pytest
from fastapi.testclient import TestClient

from backend import config, database, logstore
from backend.main import app

client = TestClient(app, base_url="http://127.0.0.1:8000")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "limits.db")
    database.init_db()
    yield


def test_events_limit_rejects_non_positive(isolated_db):
    for bad in (0, -1, -100):
        r = client.get("/api/monitor/events", params={"limit": bad})
        assert r.status_code == 422, f"limit={bad} 必须被拒绝"


def test_events_limit_rejects_too_large(isolated_db):
    r = client.get("/api/monitor/events", params={"limit": 501})
    assert r.status_code == 422
    r = client.get("/api/monitor/events", params={"limit": 500})
    assert r.status_code == 200


def test_events_limit_data_layer_clamped(isolated_db):
    # 绕过 API 层直接调数据层：负数/零被夹到 1，绝不触发 SQLite LIMIT -1 全表语义
    for i in range(5):
        database.add_watch_event("mod_new", 730, 100 + i, f"Mod {i}", "detail")
    assert len(database.list_watch_events(limit=-1)) == 1
    assert len(database.list_watch_events(limit=0)) == 1
    assert len(database.list_watch_events(limit=2)) == 2
    assert len(database.list_watch_events(limit=99999)) == 5  # 夹到 500，仍只返回实际行数


def test_logs_limit_rejected_and_clamped(isolated_db):
    r = client.get("/api/logs", params={"n": 0})
    assert r.status_code == 422
    r = client.get("/api/logs", params={"n": -5})
    assert r.status_code == 422
    r = client.get("/api/logs", params={"n": 1001})
    assert r.status_code == 422
    # 数据层：非正数不产生异常切片，也不会返回非预期内容
    logstore.add("INFO", "line-1")
    logstore.add("INFO", "line-2")
    assert len(logstore.get_recent(-3)) == 1
    assert len(logstore.get_recent(0)) == 1
    recent = logstore.get_recent(2)
    assert [line["message"] for line in recent] == ["line-1", "line-2"]


def test_claim_records_limit_rejected(isolated_db):
    r = client.get("/api/claim/records", params={"limit": -1})
    assert r.status_code == 422
    r = client.get("/api/claim/records", params={"limit": 6000})
    assert r.status_code == 422
    r = client.get("/api/claim/records")
    assert r.status_code == 200
