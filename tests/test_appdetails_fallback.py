"""Appdetails batch falls back to per-app queries only for degradable batch errors."""
import pytest

from backend import config, database
from backend.steam_client import RateLimited, SteamApiError, SteamClient, StoreBlocked


def _make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    return SteamClient("", "")


def _body(appid: int) -> dict:
    return {str(appid): {"success": True, "data": {"type": "game", "name": f"Game {appid}"}}}


def test_batch_400_falls_back_to_per_app_queries(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    calls: list[str] = []

    def fake_get(_url, params):
        calls.append(params["appids"])
        if "," in params["appids"]:
            raise SteamApiError("Steam 接口返回错误（HTTP 400）", 400)
        return _body(int(params["appids"]))

    monkeypatch.setattr(client, "_get_json", fake_get)
    result = client.get_appdetails_batch([101, 102])

    assert result[101] == {"type": "game", "name": "Game 101"}
    assert result[102] == {"type": "game", "name": "Game 102"}
    # 一次合批被拒，随后逐条兜底
    assert calls == ["101,102", "101", "102"]


def test_auth_failure_is_not_degraded(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    calls: list[str] = []

    def fake_get(_url, params):
        calls.append(params["appids"])
        raise SteamApiError("API Key 无效", 401)

    monkeypatch.setattr(client, "_get_json", fake_get)
    with pytest.raises(SteamApiError) as exc:
        client.get_appdetails_batch([201, 202])
    assert exc.value.status_code == 401
    assert calls == ["201,202"]  # 未触发逐条重试


def test_rate_limited_is_not_degraded(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    calls: list[str] = []

    def fake_get(_url, params):
        calls.append(params["appids"])
        raise RateLimited(5)

    monkeypatch.setattr(client, "_get_json", fake_get)
    with pytest.raises(RateLimited):
        client.get_appdetails_batch([301, 302])
    assert calls == ["301,302"]  # 限流属全局信号，不逐条重试


def test_store_blocked_is_not_degraded(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    calls: list[str] = []

    def fake_get(_url, params):
        calls.append(params["appids"])
        raise StoreBlocked("blocked")

    monkeypatch.setattr(client, "_get_json", fake_get)
    with pytest.raises(StoreBlocked):
        client.get_appdetails_batch([303, 304])
    assert calls == ["303,304"]  # 商店整体拦截，不逐条重试


def test_per_app_failure_is_isolated_as_none(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    calls: list[str] = []

    def fake_get(_url, params):
        calls.append(params["appids"])
        raise SteamApiError("HTTP 500", 500)

    monkeypatch.setattr(client, "_get_json", fake_get)
    result = client.get_appdetails_batch([401, 402])
    assert result == {401: None, 402: None}
    assert calls == ["401,402", "401", "402"]


def test_healthy_batch_does_not_fallback(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    calls: list[str] = []

    def fake_get(_url, params):
        calls.append(params["appids"])
        return {**_body(501), **_body(502)}

    monkeypatch.setattr(client, "_get_json", fake_get)
    result = client.get_appdetails_batch([501, 502])
    assert result[501]["name"] == "Game 501"
    assert result[502]["name"] == "Game 502"
    assert calls == ["501,502"]
