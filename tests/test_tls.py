"""TLS failures must not silently force requests.Session.verify=False."""

import pytest
from requests.exceptions import SSLError

from backend.steam_client import SteamApiError, SteamClient


def test_certificate_error_keeps_verification_enabled(monkeypatch):
    client = SteamClient("", "", verify_ssl=True)
    attempts = []

    def fail(_url, _params):
        attempts.append(client.session.verify)
        raise SSLError("bad certificate")

    monkeypatch.setattr(client, "_do_get", fail)
    with pytest.raises(SteamApiError, match="SSL"):
        client._get_json("https://store.steampowered.com/api/appdetails", {"appids": 1})
    assert attempts == [True]
    assert client.session.verify is True
