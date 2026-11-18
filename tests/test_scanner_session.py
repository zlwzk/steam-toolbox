"""scanner：线程本地 Session（线程池不再共用同一 requests.Session）与关闭中断。"""
import threading

import pytest

from backend import config, database, scanner
from backend.steam_client import SteamClient


def test_thread_local_session_isolated_per_thread():
    client = SteamClient("", "", verify_ssl=True)
    main_session = client.session
    # 同一线程重复访问复用同一 Session
    assert client.session is main_session

    seen: dict = {}

    def worker():
        seen["session"] = client.session

    t = threading.Thread(target=worker)
    t.start()
    t.join(5)

    assert seen["session"] is not main_session, "不同线程必须使用独立 Session"
    # 新 Session 保持相同安全配置（TLS 校验不丢失）
    assert seen["session"].verify == main_session.verify
    assert seen["session"].headers.get("Referer") == "https://store.steampowered.com/"


def test_thread_local_session_verify_disabled(monkeypatch):
    import backend.ca_store as ca_store
    monkeypatch.setattr(ca_store, "verify_argument", lambda v: False if v is False else "/fake/bundle.pem")
    client = SteamClient("", "", verify_ssl=False)
    assert client.session.verify is False


def test_check_pause_raises_when_abort_requested():
    scanner._abort_event.set()
    try:
        with pytest.raises(scanner.ScanAborted):
            scanner._check_pause()
    finally:
        scanner._abort_event.clear()
    # 恢复后不再抛错
    scanner._check_pause()


def test_run_scan_clears_abort(monkeypatch):
    monkeypatch.setattr(scanner, "_persist_state", lambda *a: None)
    monkeypatch.setitem(scanner.progress, "state", "idle")
    scanner._abort_event.set()

    class DummyThread:
        started = 0

        def __init__(self, **kw):
            pass

        def start(self):
            type(self).started += 1

    monkeypatch.setattr(scanner.threading, "Thread", DummyThread)
    assert scanner.run_scan("dlc") is True
    assert not scanner._abort_event.is_set(), "新扫描必须清除上一次的关闭中断信号"


def test_stop_scan_sets_abort():
    scanner._abort_event.clear()
    scanner.stop_scan()
    assert scanner._abort_event.is_set()
    scanner._abort_event.clear()


def test_concurrent_workers_use_isolated_sessions(tmp_path, monkeypatch):
    """并发 worker 各自拿到不同 Session，且共享同一客户端实例。

    用 Barrier 强制三个线程同时在线再访问 session 属性，
    确保捕获的是「并发活跃线程」各自的 Session。
    """
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "sessions.db")
    database.init_db()
    client = SteamClient("", "", verify_ssl=True)

    sessions: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(3, timeout=5)

    def fetch_block(_chunk):
        # 三个线程在此对齐，再各自取线程本地 Session
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        sess = client.session
        with lock:
            sessions.append(sess)
        return _chunk, {}, False, None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(fetch_block, [[1], [2], [3]]))

    assert len(sessions) == 3
    assert len({id(s) for s in sessions}) == 3, "3 个并发线程应各自持有独立 Session"
    # 每个 Session 的安全配置保持一致（TLS 校验与请求头不丢失）
    for s in sessions:
        assert s.verify == client.session.verify
        assert s.headers.get("Referer") == "https://store.steampowered.com/"
