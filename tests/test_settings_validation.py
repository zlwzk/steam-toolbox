from fastapi import HTTPException
import pytest

from backend import config
from backend.settings_validation import EDITABLE_KEYS, validate_settings


def test_all_current_defaults_are_valid():
    assert validate_settings({k: v for k, v in config.DEFAULT_SETTINGS.items() if k in EDITABLE_KEYS}, {})


def test_reject_private_and_unknown_keys():
    for key in ("api_key", "steamid", "cc", "last_scan_state", "made_up"):
        with pytest.raises(HTTPException) as e:
            validate_settings({key: "hijack"}, {})
        assert e.value.status_code == 422


@pytest.mark.parametrize("payload", [
    {"fetch_concurrency": "999"},
    {"fetch_delay_min": "nan"},
    {"ws_batch_size": "0"},
    {"scan_interval_minutes": "-1"},
    {"verify_ssl": "maybe"},
    {"browser_channel": "firefox"},
    {"notify_webhook": "file:///etc/passwd"},
    {"notify_webhook": "https://alice:password@host.invalid/"},
    {"fetch_delay_min": "2", "fetch_delay_max": "1"},
])
def test_reject_invalid_values(payload):
    with pytest.raises(HTTPException) as e:
        validate_settings(payload, {})
    assert e.value.status_code == 422


def test_partial_updates_and_numeric_normalization():
    assert validate_settings({"fetch_concurrency": " 4 ", "fetch_delay_max": "2.5"}, {}) == {
        "fetch_concurrency": "4", "fetch_delay_max": "2.5"
    }
