"""软件内运行日志缓冲：线程安全环形队列，供前端日志面板读取。

打包为无控制台（windowed）模式后没有 PowerShell 窗口，后端与 uvicorn 日志
统一写入这里，前端通过 /api/logs 拉取最近若干行展示。
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
from collections import deque

_MAX = 500
_buf: deque[dict] = deque(maxlen=_MAX)
_lock = threading.Lock()


def add(level: str, message: str) -> None:
    line = {
        "time": dt.datetime.now().isoformat(timespec="seconds"),
        "level": level,
        "message": str(message).strip(),
    }
    with _lock:
        _buf.append(line)


def get_recent(n: int = 300) -> list[dict]:
    with _lock:
        return list(_buf)[-n:]


def clear() -> None:
    with _lock:
        _buf.clear()


class BufferHandler(logging.Handler):
    """把 logging 记录写入环形缓冲。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            add(record.levelname, msg)
        except Exception:  # noqa: BLE001 - 日志不能影响主流程
            pass
