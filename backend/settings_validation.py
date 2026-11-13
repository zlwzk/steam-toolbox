"""Validate user-editable settings before writing them to the local database."""
from __future__ import annotations

import math
from urllib.parse import urlsplit

from fastapi import HTTPException

from . import config

_PRIVATE_KEYS = {"api_key", "steamid", "cc", "lang"}
EDITABLE_KEYS = frozenset(config.DEFAULT_SETTINGS) - _PRIVATE_KEYS

_INTEGERS = {
    "fetch_concurrency": (1, 5),
    "free_game_pages": (1, 20),
    "claim_hourly_limit": (1, 40),
    "claim_batch_size": (1, 50),
    "max_retries": (0, 10),
    "ws_batch_size": (1, 50),
    "ws_max_retries": (0, 10),
    "ws_max_pages": (1, 100),
    "scan_interval_minutes": (15, 10080),
    "watch_interval_minutes": (15, 10080),
    "watch_workshop_top": (1, 50),
}
_FLOATS = {
    "fetch_delay_min": (0.2, 120.0),
    "fetch_delay_max": (0.2, 120.0),
    "cache_ttl_hours": (0.0, 720.0),
    "claim_delay_min": (2.0, 3600.0),
    "claim_delay_max": (2.0, 3600.0),
    "batch_rest_min": (0.0, 7200.0),
    "batch_rest_max": (0.0, 7200.0),
    "ws_delay_min": (1.0, 600.0),
    "ws_delay_max": (1.0, 600.0),
    "ws_cooldown_min": (0.0, 7200.0),
    "ws_cooldown_max": (0.0, 7200.0),
}
_CHOICES = {
    "auto_claim": {"true", "false"},
    "verify_ssl": {"true", "false"},
    "claim_headless": {"true", "false"},
    "auto_scan": {"true", "false"},
    "notify_on_done": {"true", "false"},
    "ws_cooldown_enabled": {"true", "false"},
    "browser_channel": {"msedge", "chrome", "chromium"},
    "scan_kind": {"dlc", "freegame", "both"},
    "cleaner_unit": {"minute", "hour"},
    "cleaner_exclude_delisted": {"keep", "exclude", "only"},
    "watch_auto": {"true", "false"},
    "watch_auto_subscribe": {"true", "false"},
}
_RANGES = (
    ("fetch_delay_min", "fetch_delay_max"),
    ("claim_delay_min", "claim_delay_max"),
    ("batch_rest_min", "batch_rest_max"),
    ("ws_delay_min", "ws_delay_max"),
    ("ws_cooldown_min", "ws_cooldown_max"),
)


def validate_settings(payload: dict, current: dict[str, str]) -> dict[str, str]:
    """Normalize a whole or partial settings update, rejecting invalid values atomically."""
    if not isinstance(payload, dict):
        raise HTTPException(422, "设置应为对象")
    result: dict[str, str] = {}
    for key, raw in payload.items():
        if key not in EDITABLE_KEYS:
            raise HTTPException(422, f"不允许修改设置项：{key}")
        if not isinstance(raw, (str, int, float)) or isinstance(raw, bool):
            raise HTTPException(422, f"{key} 值类型错误")
        value = str(raw).strip()
        if key in _INTEGERS:
            lo, hi = _INTEGERS[key]
            try:
                n = int(value)
            except ValueError:
                raise HTTPException(422, f"{key} 应为整数") from None
            if not lo <= n <= hi:
                raise HTTPException(422, f"{key} 范围应为 {lo}–{hi}")
            value = str(n)
        elif key in _FLOATS:
            lo, hi = _FLOATS[key]
            try:
                n = float(value)
            except ValueError:
                raise HTTPException(422, f"{key} 应为数字") from None
            if not math.isfinite(n) or not lo <= n <= hi:
                raise HTTPException(422, f"{key} 范围应为 {lo}–{hi}")
            value = str(n)
        elif key in _CHOICES:
            if value not in _CHOICES[key]:
                raise HTTPException(422, f"{key} 的选项无效")
        elif key == "notify_webhook":
            if len(value) > 2048:
                raise HTTPException(422, "Webhook 地址过长")
            if value:
                try:
                    parsed = urlsplit(value)
                    host = parsed.hostname
                    _ = parsed.port  # Reject malformed/out-of-range ports.
                except ValueError:
                    raise HTTPException(422, "Webhook 地址格式无效") from None
                if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
                    raise HTTPException(422, "Webhook 必须是合法的 http(s) 地址且不能包含账号密码")
        else:
            raise HTTPException(422, f"未定义校验规则：{key}")
        result[key] = value

    combined = {**config.DEFAULT_SETTINGS, **current, **result}
    for low_key, high_key in _RANGES:
        try:
            low, high = float(combined[low_key]), float(combined[high_key])
        except (ValueError, TypeError):
            raise HTTPException(422, f"{low_key}/{high_key} 的历史值无效，请重设") from None
        if not (math.isfinite(low) and math.isfinite(high) and low <= high):
            raise HTTPException(422, f"{low_key} 不能大于 {high_key}")
    return result
