"""限速与退避调度器（线程安全）。

抓取与领取共用一套节奏控制：全局请求闸门、随机间隔、按小时预算、429/5xx 退避。
核心原则：低频、随机、可退避、遇阻即停；并发线程通过同一把闸门串行化
「请求发出」的时刻，避免首批请求扎堆触发 Steam 限流。
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass


@dataclass
class ThrottleConfig:
    delay_min: float
    delay_max: float
    hourly_limit: int | None = None
    max_retries: int = 2


class Throttler:
    def __init__(self, cfg: ThrottleConfig):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._last_sent = 0.0
        self._window_start = time.monotonic()
        self._claimed_in_window = 0

    def gate(self) -> None:
        """发真实请求前的全局节奏闸门（线程安全）。

        并发 worker 都先过这里：保证距上一次发出请求至少间隔 ``delay_min``，
        再叠加一段随机抖动，避免多线程同时把首批请求扎堆发出。
        """
        with self._lock:
            elapsed = time.monotonic() - self._last_sent
            if elapsed < self.cfg.delay_min:
                time.sleep(self.cfg.delay_min - elapsed)
            self._last_sent = time.monotonic()
        # 随机抖动放在锁外，进一步打散节奏，不占用临界区
        jitter = max(0.0, self.cfg.delay_max - self.cfg.delay_min)
        if jitter > 0:
            time.sleep(random.uniform(0, jitter))

    def wait_random_delay(self) -> None:
        """单次动作前的随机间隔（串行场景直接使用）。"""
        time.sleep(random.uniform(self.cfg.delay_min, self.cfg.delay_max))

    def check_hourly_budget(self) -> bool:
        """是否还有本小时领取预算；超时窗口自动重置。"""
        if self.cfg.hourly_limit is None:
            return True
        if time.monotonic() - self._window_start > 3600:
            self._window_start = time.monotonic()
            self._claimed_in_window = 0
        return self._claimed_in_window < self.cfg.hourly_limit

    def mark_consumed(self) -> None:
        self._claimed_in_window += 1

    @staticmethod
    def compute_backoff(attempt: int, retry_after: float | None = None) -> float:
        """计算退避秒数：优先 Retry-After，否则指数退避并加随机抖动，封顶 300s。"""
        if retry_after is not None and retry_after > 0:
            return min(float(retry_after), 300.0)
        base = min(30 * (2 ** max(0, attempt)), 300)
        return min(base * random.uniform(1.0, 1.3), 300.0)

    def backoff(self, attempt: int, retry_after: float | None = None) -> float:
        """失败退避：优先 Retry-After，否则指数退避加抖动。返回实际等待秒数。"""
        delay = self.compute_backoff(attempt, retry_after)
        time.sleep(delay)
        return delay
