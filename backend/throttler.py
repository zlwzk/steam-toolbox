"""限速与退避调度器。

抓取与领取共用一套节奏控制：随机间隔、按小时预算、429 退避。
领取阶段严格串行；MVP 尚未接入真实领取，接口先预留。
"""
from __future__ import annotations

import random
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
        self._window_start = time.monotonic()
        self._claimed_in_window = 0

    def wait_random_delay(self) -> None:
        """单次动作前的随机间隔。"""
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

    def backoff(self, attempt: int, retry_after: float | None = None) -> float:
        """失败退避：优先 Retry-After，否则指数退避。返回实际等待秒数。"""
        if retry_after is not None and retry_after > 0:
            time.sleep(retry_after)
            return retry_after
        # 30s -> 60s -> 120s 指数退避，封顶 300s
        delay = min(30 * (2 ** attempt), 300)
        time.sleep(delay)
        return delay
