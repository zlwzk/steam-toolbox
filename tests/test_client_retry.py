"""请求层瞬时重试：429 / 5xx 有限次退避重试，401/403 立即抛出不重试。"""

from types import SimpleNamespace

import pytest

from backend.steam_client import RateLimited, SteamApiError, SteamClient


def _resp(status: int, payload: dict | None = None, headers: dict | None = None):
    return SimpleNamespace(
        status_code=status,
        headers=headers or {},
        json=lambda: payload or {"response": {}},
        text="",
        raise_for_status=lambda: None,
    )


def _client():
    return SteamClient("", "", verify_ssl=True)


def test_429_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr("backend.steam_client.time.sleep", lambda _s: None)
    client = _client()
    seq = [_resp(429), _resp(429), _resp(200, {"ok": True})]
    calls = []

    def fake_get(_url, _params):
        calls.append(1)
        return seq.pop(0)

    monkeypatch.setattr(client, "_do_get", fake_get)
    out = client._get_json("https://api.steampowered.com/x", {})
    assert out == {"ok": True}
    assert len(calls) == 3


def test_429_exhausts_raises_rate_limited(monkeypatch):
    monkeypatch.setattr("backend.steam_client.time.sleep", lambda _s: None)
    client = _client()

    def fake_get(_url, _params):
        return _resp(429)

    monkeypatch.setattr(client, "_do_get", fake_get)
    with pytest.raises(RateLimited):
        client._get_json("https://api.steampowered.com/x", {})


def test_5xx_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr("backend.steam_client.time.sleep", lambda _s: None)
    client = _client()
    seq = [_resp(503), _resp(502), _resp(200, {"ok": True})]
    calls = []

    def fake_get(_url, _params):
        calls.append(1)
        return seq.pop(0)

    monkeypatch.setattr(client, "_do_get", fake_get)
    out = client._get_json("https://store.steampowered.com/api/appdetails", {})
    assert out == {"ok": True}
    assert len(calls) == 3


def test_401_is_not_retried(monkeypatch):
    monkeypatch.setattr("backend.steam_client.time.sleep", lambda _s: None)
    client = _client()
    calls = []

    def fake_get(_url, _params):
        calls.append(1)
        return _resp(401)

    monkeypatch.setattr(client, "_do_get", fake_get)
    with pytest.raises(SteamApiError) as exc:
        client._get_json("https://api.steampowered.com/x", {})
    assert exc.value.status_code == 401
    assert len(calls) == 1
