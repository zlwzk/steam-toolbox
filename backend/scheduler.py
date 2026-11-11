"""定时巡检调度器：按配置周期自动触发 DLC / 喜加一扫描。

- 后台守护线程，每 60s 检查一次是否到点
- 扫描进行中本轮跳过；both 模式下 DLC 与喜加一交替执行
- 开关、间隔、范围均在设置页配置
"""
from __future__ import annotations

import datetime as dt
import threading

from . import database, scanner

_state: dict = {
    "enabled": False,
    "interval_minutes": 360,
    "kind": "both",
    "last_run_at": None,
    "last_kind": None,
    "next_run_at": None,
}
_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None


def get_status() -> dict:
    with _lock:
        return dict(_state)


def _tick() -> None:
    enabled = database.get_setting("auto_scan", "false").lower() == "true"
    try:
        interval = int(database.get_setting("scan_interval_minutes", "360"))
    except ValueError:
        interval = 360
    kind = database.get_setting("scan_kind", "both")

    with _lock:
        _state["enabled"] = enabled
        _state["interval_minutes"] = interval
        _state["kind"] = kind

    if not enabled or scanner.progress["state"] in ("running", "paused"):
        return

    last = _state["last_run_at"]
    due = last is None or (dt.datetime.now() - dt.datetime.fromisoformat(last)).total_seconds() >= interval * 60
    if not due:
        return

    if kind == "dlc":
        target = "dlc"
    elif kind == "freegame":
        target = "freegame"
    else:
        target = "freegame" if _state.get("last_kind") == "dlc" else "dlc"

    scanner.run_scan(target)
    with _lock:
        _state["last_run_at"] = dt.datetime.now().isoformat(timespec="seconds")
        _state["last_kind"] = target
        _state["next_run_at"] = (dt.datetime.now() + dt.timedelta(minutes=interval)).isoformat(timespec="seconds")


def _loop() -> None:
    while not _stop.is_set():
        try:
            _tick()
        except Exception:  # noqa: BLE001 - 调度循环不能因单次异常退出
            pass
        _stop.wait(60)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
