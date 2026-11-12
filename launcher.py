"""PyInstaller 打包入口：启动本地后端并自动打开浏览器页面。

打包为无控制台（windowed）模式后没有 PowerShell 窗口：标准输出兜底到内存，
后端与 uvicorn 日志写入软件内日志缓冲，前端「运行日志」面板查看。

开发调试仍可用：python -m uvicorn backend.main:app --port 8000
"""
from __future__ import annotations

import io
import logging
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from backend import logstore
from backend.main import app

HOST = "127.0.0.1"
PORT = 8000


def _ensure_stdio() -> None:
    """无控制台模式下 sys.stdout/stderr 可能为 None，兜底避免写日志崩溃。"""
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()


def _setup_logging() -> None:
    handler = logstore.BufferHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False


def _health_ok() -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/health", timeout=2) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def _existing_instance() -> bool:
    """端口已被占用且 /api/health 正常，说明已有本工具实例在运行。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        if sock.connect_ex((HOST, PORT)) != 0:
            return False
    finally:
        sock.close()
    return _health_ok()


def _open_browser() -> None:
    # 等待后端就绪再打开页面，避免浏览器先于服务启动而出现「连接被拒」
    for _ in range(20):  # 最多约 10 秒
        if _health_ok():
            break
        time.sleep(0.5)
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    _ensure_stdio()
    _setup_logging()
    if _existing_instance():
        # 已有实例在跑：直接把浏览器指过去，不再重复起服务，避免端口冲突
        webbrowser.open(f"http://{HOST}:{PORT}")
    else:
        threading.Thread(target=_open_browser, daemon=True).start()
        try:
            # log_config=None：不覆盖上面挂到日志缓冲的 handler；access_log=False 不打访问日志
            uvicorn.run(app, host=HOST, port=PORT, log_level="info",
                        access_log=False, log_config=None)
        except OSError as exc:  # 端口被占用等启动失败：写进软件日志缓冲，便于在界面排查
            logstore.add("ERROR", f"本地服务启动失败（端口 {PORT} 可能被占用）：{exc}")
