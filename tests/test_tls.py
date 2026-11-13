"""TLS 失败不得静默关闭证书校验；校验开启时仍走受信 CA bundle。"""

import pytest
from requests.exceptions import SSLError

from backend import ca_store
from backend.steam_client import SteamApiError, SteamClient


def test_certificate_error_keeps_verification_enabled(monkeypatch):
    monkeypatch.setattr(ca_store, "bundle_path", lambda: "/fake/ca-bundle.pem")
    client = SteamClient("", "", verify_ssl=True)
    attempts = []

    def fail(_url, _params):
        attempts.append(client.session.verify)
        raise SSLError("bad certificate")

    monkeypatch.setattr(client, "_do_get", fail)
    with pytest.raises(SteamApiError, match="SSL"):
        client._get_json("https://store.steampowered.com/api/appdetails", {"appids": 1})
    # 校验开启：verify 为受信 bundle 路径，绝不是 False
    assert attempts == ["/fake/ca-bundle.pem"]
    assert client.session.verify is not False


def test_verify_disabled_returns_false(monkeypatch):
    monkeypatch.setattr(ca_store, "bundle_path", lambda: "/fake/ca-bundle.pem")
    client = SteamClient("", "", verify_ssl=False)
    assert client.session.verify is False
