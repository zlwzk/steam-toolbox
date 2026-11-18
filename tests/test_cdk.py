"""CDK 登记回归测试：格式校验、掩码、状态机、不自动提交、明文不落日志。"""
import pytest
from fastapi.testclient import TestClient

from backend import config, database, logstore
from backend.cdk import mask, validate_format
from backend.main import app


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cdk.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    database.init_db()
    yield


client = TestClient(app, base_url="http://127.0.0.1:8000")

VALID_5 = "ABCDE-FGHIJ-KLMNO-PQRST-VWXYZ"
VALID_3 = "abcde-fghij-klmno"


# ---------- 格式校验 ----------

@pytest.mark.parametrize("key,valid", [
    (VALID_5, True),
    (VALID_3, True),          # 3 组（老 CD / 预载 key 较短）
    ("", False),
    ("bad key!!", False),
    ("A-B", False),           # 每组至少 3 位
    ("ABCDEFGHIJKLMNOPQRSTUVWXY", False),  # 无连字符
    ("x" * 70, False),        # 超长
])
def test_validate_format(key, valid):
    ok_fmt, _ = validate_format(key)
    assert ok_fmt is valid


def test_mask_keeps_first_group_only():
    assert mask(VALID_5) == "ABCDE-•••••-•••••-•••••-•••••"
    assert mask(VALID_3) == "abcde-•••••-•••••"
    assert mask("") == "•••"


# ---------- API：登记 / 列表 / 去重 ----------

def test_add_and_list(isolated):
    r = client.post("/api/cdk/add", json={"keys": [VALID_5, "bad key!!"], "note": "n1"})
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == 1 and body["invalid"] == 1
    # 明文绝不回显，只有掩码
    assert all(VALID_5 not in str(i) for i in body["items"])

    lst = client.get("/api/cdk/list").json()
    assert lst["counts"] == {"ready": 1, "invalid": 1}
    assert all(VALID_5 not in str(i) for i in lst["items"])


def test_add_duplicate_rejected(isolated):
    client.post("/api/cdk/add", json={"keys": [VALID_5]})
    r = client.post("/api/cdk/add", json={"keys": [VALID_5]})
    assert r.json()["duplicate"] == 1
    assert client.get("/api/cdk/list").json()["total"] == 1


def test_add_empty_rejected(isolated):
    assert client.post("/api/cdk/add", json={"keys": []}).status_code == 422


# ---------- 状态机：确认 / 手动标记 / 不自动写成功 ----------

def test_confirm_revalidates_format(isolated):
    client.post("/api/cdk/add", json={"keys": [VALID_5, "bad key!!"]})
    keys = [i["id"] for i in client.get("/api/cdk/list").json()["items"]]
    r = client.post("/api/cdk/confirm", json={"ids": keys})
    body = r.json()
    assert body["confirmed"] == 1  # 仅格式合格那条


def test_activated_never_automatic(isolated):
    """确认（confirm）永远不会把条目变成 activated。"""
    client.post("/api/cdk/add", json={"keys": [VALID_5]})
    kid = client.get("/api/cdk/list").json()["items"][0]["id"]
    client.post("/api/cdk/confirm", json={"ids": [kid]})
    lst = client.get("/api/cdk/list").json()
    assert lst["counts"].get("activated", 0) == 0
    assert lst["counts"]["ready"] == 1


def test_manual_mark_activated(isolated):
    client.post("/api/cdk/add", json={"keys": [VALID_5]})
    kid = client.get("/api/cdk/list").json()["items"][0]["id"]
    r = client.post("/api/cdk/status", json={"id": kid, "status": "activated"})
    assert r.json()["ok"] is True
    assert client.get("/api/cdk/list").json()["counts"]["activated"] == 1


def test_manual_mark_invalid_status_rejected(isolated):
    client.post("/api/cdk/add", json={"keys": [VALID_5]})
    kid = client.get("/api/cdk/list").json()["items"][0]["id"]
    r = client.post("/api/cdk/status", json={"id": kid, "status": "hacked"})
    assert r.status_code == 400


def test_terminal_status_skipped_in_confirm(isolated):
    client.post("/api/cdk/add", json={"keys": [VALID_5]})
    kid = client.get("/api/cdk/list").json()["items"][0]["id"]
    client.post("/api/cdk/status", json={"id": kid, "status": "activated"})
    r = client.post("/api/cdk/confirm", json={"ids": [kid]})
    assert r.json()["skipped"] == 1


# ---------- 明文取回与隐私 ----------

def test_reveal_single_key_with_audit_no_plaintext_in_log(isolated):
    client.post("/api/cdk/add", json={"keys": [VALID_5]})
    kid = client.get("/api/cdk/list").json()["items"][0]["id"]
    r = client.get(f"/api/cdk/reveal/{kid}")
    assert r.json()["key"] == VALID_5
    # 审计日志只落掩码/ID，绝不落明文
    logs = "\n".join(str(l) for l in logstore.get_recent(100))
    assert VALID_5 not in logs


def test_remove_key(isolated):
    client.post("/api/cdk/add", json={"keys": [VALID_5]})
    kid = client.get("/api/cdk/list").json()["items"][0]["id"]
    assert client.delete(f"/api/cdk/{kid}").status_code == 200
    assert client.get("/api/cdk/list").json()["total"] == 0
    assert client.delete(f"/api/cdk/{kid}").status_code == 404


def test_activate_info_route(isolated):
    response = client.get("/api/cdk/activate-info")
    assert response.status_code == 200
    assert response.json()["web_url"].startswith("https://store.steampowered.com/")


def test_invalid_code_cannot_be_marked_activated(isolated):
    client.post("/api/cdk/add", json={"keys": ["bad key!!"]})
    kid = client.get("/api/cdk/list").json()["items"][0]["id"]
    response = client.post("/api/cdk/status", json={"id": kid, "status": "activated"})
    assert response.status_code == 400


def test_no_network_side_effect(isolated, monkeypatch):
    """登记 / 确认 / 标记全程不得发起任何外部 HTTP 请求。"""
    import backend.steam_client as sc

    calls = []

    class _Boom:
        def __getattr__(self, name):
            calls.append(name)
            raise AssertionError(f"不应发起网络请求：{name}")

    monkeypatch.setattr(sc.SteamClient, "_get_json", _Boom())
    client.post("/api/cdk/add", json={"keys": [VALID_5]})
    kid = client.get("/api/cdk/list").json()["items"][0]["id"]
    client.post("/api/cdk/confirm", json={"ids": [kid]})
    client.post("/api/cdk/status", json={"id": kid, "status": "failed", "reason": "test"})
    assert not calls
