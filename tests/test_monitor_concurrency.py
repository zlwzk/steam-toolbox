"""monitor.run_check 原子化：并发请求同一时刻只启动一个 worker；启动失败恢复状态。"""
import threading
import time

import pytest
from fastapi import HTTPException

from backend import config, database, logstore, monitor


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "monitor_conc.db")
    database.init_db()
    database.update_settings({"api_key": "test-key", "steamid": "76561190000000000"})
    # 清理可能残留的运行态
    monitor._update(state="idle")
    yield
    monitor._update(state="idle")


class _BlockingWorker:
    """记录被启动次数，并在首次进入时挂起，放大并发窗口。"""

    def __init__(self):
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self):
        self.calls += 1
        self.entered.set()
        self.release.wait(5)


def test_concurrent_run_check_starts_single_worker(isolated_db, monkeypatch):
    worker = _BlockingWorker()
    monkeypatch.setattr(monitor, "_check_worker", worker)

    results: list[dict] = []
    rlock = threading.Lock()

    def caller():
        out = monitor.run_check()
        with rlock:
            results.append(out)

    threads = [threading.Thread(target=caller) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert worker.entered.wait(5)
    worker.release.set()

    assert worker.calls == 1, "同一时刻只能启动一个监控 worker"
    ok = [r for r in results if r.get("ok")]
    rejected = [r for r in results if not r.get("ok")]
    assert len(ok) == 1
    assert len(rejected) == 7
    assert all(r.get("error") == "监控检测正在进行中" for r in rejected)


def test_second_check_rejected_while_running(isolated_db, monkeypatch):
    worker = _BlockingWorker()
    monkeypatch.setattr(monitor, "_check_worker", worker)
    assert monitor.run_check()["ok"] is True
    second = monitor.run_check()
    assert second["ok"] is False
    worker.release.set()


def test_run_check_without_credentials_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "monitor_nocred.db")
    database.init_db()
    monitor._update(state="idle")
    out = monitor.run_check()
    assert out["ok"] is False
    assert "账号绑定" in out["error"]


class _FailingThread:
    """线程 start 失败：模拟资源耗尽等场景。"""

    def __init__(self, *a, **kw):
        pass

    def start(self):
        raise RuntimeError("cannot start new thread")


def test_thread_start_failure_restores_error_state(isolated_db, monkeypatch):
    monkeypatch.setattr(monitor, "threading", threading)
    monkeypatch.setattr(monitor.threading, "Thread", _FailingThread)
    out = monitor.run_check()
    assert out["ok"] is False
    assert "启动监控检测失败" in out["error"]
    prog = monitor.get_progress()
    assert prog["state"] == "error", "启动失败不得残留 running 状态"
    assert prog["finished_at"]
    # 错误写入日志，不静默
    assert any("启动失败" in line["message"] for line in logstore.get_recent(50))


def test_stop_sets_event_and_joins_thread(isolated_db, monkeypatch):
    monkeypatch.setattr(monitor, "_tick", lambda: None)
    monitor.start()
    thread = monitor._thread
    assert thread is not None and thread.is_alive()
    monitor.stop()
    assert monitor._thread is None
    assert not thread.is_alive(), "停止后循环线程应已退出"
    # 重复 start 不会创建第二个循环线程
    monitor.start()
    t1 = monitor._thread
    monitor.start()
    assert monitor._thread is t1
    monitor.stop()
