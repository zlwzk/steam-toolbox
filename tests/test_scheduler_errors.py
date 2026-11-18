"""scheduler：后台循环异常必须留痕（日志 + 状态），循环保持韧性；stop 可等待退出。"""
import threading
import time

import pytest

from backend import config, database, logstore, scheduler


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "sched.db")
    database.init_db()
    yield
    scheduler.stop()


def test_loop_exception_recorded_and_loop_survives(monkeypatch):
    calls = {"n": 0}

    def flaky_tick():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return None

    monkeypatch.setattr(scheduler, "_tick", flaky_tick)
    scheduler.start()

    deadline = time.time() + 3
    while time.time() < deadline:
        status = scheduler.get_status()
        if status.get("last_error"):
            break
        time.sleep(0.05)

    status = scheduler.get_status()
    assert status["last_error"], "循环异常必须记录到状态，不能静默 pass"
    assert "boom" in status["last_error"]
    assert status["last_error_at"]
    # 日志中留有 ERROR
    assert any(line["level"] == "ERROR" and "boom" in line["message"]
               for line in logstore.get_recent(50))
    # 循环韧性：异常后仍在运行
    assert scheduler._thread is not None and scheduler._thread.is_alive()


def test_stop_joins_loop_thread():
    scheduler.start()
    thread = scheduler._thread
    assert thread.is_alive()
    scheduler.stop()
    assert scheduler._thread is None
    assert not thread.is_alive()


def test_status_contains_error_fields():
    status = scheduler.get_status()
    for key in ("enabled", "interval_minutes", "kind", "last_run_at",
                "last_kind", "next_run_at", "last_error", "last_error_at"):
        assert key in status
