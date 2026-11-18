"""lifespan：启动初始化数据库与后台线程；关闭发停止信号并等待退出；不重复启动。"""
import threading

import pytest
from fastapi.testclient import TestClient

from backend import config, database, monitor, scheduler, scanner
from backend.main import app

# base_url 指向本机回环，满足 localhost 安全边界校验
client = TestClient(app, base_url="http://127.0.0.1:8000")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "lifespan.db")
    yield
    scheduler.stop()
    monitor.stop()


def test_lifespan_startup_and_shutdown(isolated_db):
    with client:
        assert client.get("/api/health").json()["ok"] is True
        # 启动后数据库与后台循环线程就绪
        assert (config.DB_PATH).exists()
        assert scheduler._thread is not None and scheduler._thread.is_alive()
        assert monitor._thread is not None and monitor._thread.is_alive()

    # 关闭后：线程引用清空且已退出，无遗留运行态
    assert scheduler._thread is None
    assert monitor._thread is None
    assert monitor.get_progress()["state"] in ("idle", "error", "done", "blocked")
    assert scanner.get_progress()["state"] in ("idle", "error", "done")


def test_start_idempotent_no_duplicate_threads(isolated_db):
    database.init_db()
    scheduler.start()
    t1 = scheduler._thread
    scheduler.start()
    assert scheduler._thread is t1
    scheduler.stop()
    monitor.start()
    m1 = monitor._thread
    monitor.start()
    assert monitor._thread is m1
    monitor.stop()


def test_monitor_stop_interrupts_running_check(isolated_db, monkeypatch):
    """关闭时进行中的检测被中断并落为错误态，不伪称完成。"""
    database.init_db()
    database.update_settings({"api_key": "k", "steamid": "76561190000000000"})
    monitor._update(state="idle")
    started = threading.Event()
    release = threading.Event()

    def slow_worker():
        started.set()
        release.wait(5)
        # 与 _check_worker 一致：断点处检查停止信号后收尾为错误态
        if monitor._stop.is_set():
            monitor._update(state="error", message="监控检测随软件关闭而中断")

    monkeypatch.setattr(monitor, "_check_worker", slow_worker)
    assert monitor.run_check()["ok"] is True
    assert started.wait(5)
    monitor.stop()
    release.set()
    # worker 完成收尾需要一点时间：轮询等待状态落定
    import time
    deadline = time.time() + 5
    while time.time() < deadline and monitor.get_progress()["state"] != "error":
        time.sleep(0.05)
    prog = monitor.get_progress()
    assert prog["state"] == "error"
    assert "软件关闭" in prog["message"]
