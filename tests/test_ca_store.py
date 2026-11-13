"""CA bundle 装配：PEM 抽取、校验开关语义与跨平台回退。"""

import certifi

from backend import ca_store


def test_extract_pem_blocks_keeps_only_complete_certs():
    text = (
        "some noisy log line\n"
        "-----BEGIN CERTIFICATE-----\n"
        "MIIBfakeone\n"
        "-----END CERTIFICATE-----\n"
        "-----BEGIN CERTIFICATE-----\n"
        "MIIBfaketwo\n"
        "-----END CERTIFICATE-----\n"
        "trailing junk\n"
    )
    blocks = ca_store._extract_pem_blocks(text)
    assert blocks.count("BEGIN CERTIFICATE") == 2
    assert "MIIBfakeone" in blocks
    assert "MIIBfaketwo" in blocks
    assert "noisy log" not in blocks
    assert "trailing junk" not in blocks


def test_extract_pem_drops_truncated_block():
    text = (
        "-----BEGIN CERTIFICATE-----\n"
        "MIIBtruncated\n"
        "-----END CERTIFICATE-----\n"
        "-----BEGIN CERTIFICATE-----\n"
        "MIIBmissingend\n"
    )
    blocks = ca_store._extract_pem_blocks(text)
    assert blocks.count("BEGIN CERTIFICATE") == 1
    assert "MIIBtruncated" in blocks
    assert "MIIBmissingend" not in blocks


def test_verify_argument_disabled_is_false():
    assert ca_store.verify_argument(False) is False


def test_verify_argument_enabled_uses_bundle(monkeypatch):
    monkeypatch.setattr(ca_store, "bundle_path", lambda: "/tmp/ca-bundle.pem")
    assert ca_store.verify_argument(True) == "/tmp/ca-bundle.pem"


def test_non_windows_falls_back_to_certifi(monkeypatch):
    monkeypatch.setattr(ca_store.os, "name", "posix")
    ca_store.bundle_path.cache_clear()
    try:
        assert ca_store.bundle_path() == certifi.where()
    finally:
        ca_store.bundle_path.cache_clear()
