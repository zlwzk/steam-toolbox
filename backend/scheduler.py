"""定时巡检调度器：按配置周期自动触发 DLC / 喜加一扫描。

- 后台守护线程，每 5s 检查一次是否到点（粒度兼顾响应与开销）
- 扫描进行中本轮跳过；both 模式下 DLC 与喜加一交替执行
- 开关、间隔、范围均在设置页配置
- 循环内异常记录到日志与状态（last_error / last_error_at），不静默消失
"""
from __future__ import annotations

import datetime as dt
import threading

from . import database, logstore, scanner

_state: dict = {
    "enabled": False,
    "interval_minutes": 360,
    "kind": "both",
    "last_run_at": None,
    "last_kind": None,
    "next_run_at": None,
    "last_error": None,
    "last_error_at": None,
}
_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_LOOP_INTERVAL = 5.0  # 秒；同时决定关闭时等待线程退出的上限


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
        _state["next_run_at"] = _planned_next(interval)

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


def _planned_next(interval: int) -> str | None:
    """根据上次运行时间推算下次计划时间；未启用/未运行过时为 None。"""
    last = _state["last_run_at"]
    if last is None:
        return None
    try:
        return (dt.datetime.fromisoformat(last) + dt.timedelta(minutes=interval)).isoformat(timespec="seconds")
    except ValueError:
        return None


def _record_error(exc: Exception) -> None:
    """循环异常落日志与状态：保留循环韧性，但错误不能静默消失。"""
    message = f"定时巡检调度异常：{exc}"
    logstore.add("ERROR", message)
    with _lock:
        _state["last_error"] = message
        _state["last_error_at"] = dt.datetime.now().isoformat(timespec="seconds")


def _loop() -> None:
    while not _stop.is_set():
        try:
            _tick()
        except Exception as exc:  # noqa: BLE001 - 调度循环不能因单次异常退出，但必须留痕
            _record_error(exc)
        _stop.wait(_LOOP_INTERVAL)


def start() -> None:
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, daemon=True)
        _thread.start()


def stop() -> None:
    """发出停止信号并等待循环线程退出；重复调用安全。"""
    global _thread
    _stop.set()
    thread = _thread
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=_LOOP_INTERVAL + 1.0)
    with _lock:
        _thread = None
