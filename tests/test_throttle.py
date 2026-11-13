"""限速闸门与退避计算：线程安全间隔、Retry-After 优先、指数封顶与抖动。"""

import time

from backend.throttler import ThrottleConfig, Throttler


def test_gate_enforces_minimum_interval():
    thr = Throttler(ThrottleConfig(delay_min=0.05, delay_max=0.05))
    thr.gate()
    start = time.monotonic()
    thr.gate()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.05 - 1e-3


def test_compute_backoff_prefers_retry_after_and_caps():
    assert Throttler.compute_backoff(0, retry_after=12) == 12
    # 超长 Retry-After 封顶 300s
    assert Throttler.compute_backoff(0, retry_after=9999) == 300.0


def test_compute_backoff_exponential_with_jitter():
    for attempt in range(3):
        base = min(30 * (2 ** attempt), 300)
        val = Throttler.compute_backoff(attempt)
        assert base <= val <= base * 1.3 + 1e-6


def test_compute_backoff_caps_at_300():
    assert Throttler.compute_backoff(10) <= 300.0
