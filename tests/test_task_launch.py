"""Double-click/repeated API calls must not spawn duplicate workers."""
import ast
from pathlib import Path

from backend import claimer, cleaner, scanner


class DummyThread:
    started = 0

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def start(self):
        type(self).started += 1


def test_scanner_duplicate_start(monkeypatch):
    DummyThread.started = 0
    monkeypatch.setattr(scanner.threading, "Thread", DummyThread)
    monkeypatch.setattr(scanner, "_persist_state", lambda *a: None)
    monkeypatch.setitem(scanner.progress, "state", "idle")
    assert scanner.run_scan("dlc") is True
    assert scanner.run_scan("dlc") is False
    assert DummyThread.started == 1


def test_claimer_duplicate_start(monkeypatch):
    DummyThread.started = 0
    monkeypatch.setattr(claimer.threading, "Thread", DummyThread)
    monkeypatch.setattr(claimer.database, "save_claim_queue", lambda items: None)
    monkeypatch.setitem(claimer.claim_progress, "state", "idle")
    assert claimer.start_claim([{"appid": 10, "kind": "dlc"}]) is True
    assert claimer.start_claim([{"appid": 11, "kind": "dlc"}]) is False
    assert DummyThread.started == 1


def test_cleaner_duplicate_start(monkeypatch):
    DummyThread.started = 0
    monkeypatch.setattr(cleaner.threading, "Thread", DummyThread)
    monkeypatch.setitem(cleaner.cleaner_progress, "state", "idle")
    assert cleaner.analyze({"time_mode": "never"})["ok"] is True
    assert cleaner.analyze({"time_mode": "never"})["ok"] is False
    assert DummyThread.started == 1


def test_workshop_callers_unpack_three_browser_results():
    source = (Path(__file__).resolve().parents[1] / "backend" / "workshop.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    launch_assignments = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "_launch_context"
    ]
    assert len(launch_assignments) == 2
    assert all(len(node.targets) == 1 and isinstance(node.targets[0], ast.Tuple)
               and len(node.targets[0].elts) == 3 for node in launch_assignments)
