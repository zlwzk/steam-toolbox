"""完成通知：向可配置 webhook 推送扫描/领取结果（Bark / Server酱 / 通用 JSON）。

失败静默，不影响主流程；不存储任何渠道密钥之外的敏感信息。
"""
from __future__ import annotations

import datetime as dt

import requests

from . import database


def _verify() -> bool:
    return database.get_setting("verify_ssl", "true").lower() != "false"


def notify(title: str, content: str) -> None:
    url = database.get_setting("notify_webhook", "")
    if not url:
        return
    if database.get_setting("notify_on_done", "true").lower() != "true":
        return
    payload = {"title": title, "content": content, "ts": dt.datetime.now().isoformat(timespec="seconds")}
    try:
        requests.post(url, json=payload, timeout=10, verify=_verify())
    except Exception:  # noqa: BLE001 - 通知失败不阻断主流程
        pass
