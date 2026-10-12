import random
import threading
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime


class RateLimiter:
    """
    Shared across download threads.

    - `before_request()` spaces request starts at least `min_gap` seconds apart.
    - `consume(n)` is a token bucket that holds total throughput to `bytes_per_sec`
      (0 disables it).
    """

    def __init__(self, bytes_per_sec: float = 0.0, min_gap: float = 0.0, clock=time.monotonic, sleep=time.sleep) -> None:
        self.bytes_per_sec = max(0.0, float(bytes_per_sec))
        self.min_gap = max(0.0, float(min_gap))
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_request_at = 0.0
        self._tokens = self.bytes_per_sec
        self._last_refill = clock()

    @classmethod
    def from_settings(cls, rate_limit_mb_s: float, min_request_gap_ms: int) -> "RateLimiter":
        return cls(bytes_per_sec=rate_limit_mb_s * 1024 * 1024, min_gap=min_request_gap_ms / 1000.0)

    def before_request(self) -> None:
        if self.min_gap <= 0:
            return
        with self._lock:
            now = self._clock()
            start = max(now, self._next_request_at)
            self._next_request_at = start + self.min_gap
        wait = start - now
        if wait > 0:
            self._sleep(wait)

    def consume(self, nbytes: int) -> None:
        if self.bytes_per_sec <= 0 or nbytes <= 0:
            return
        with self._lock:
            now = self._clock()
            self._tokens = min(self.bytes_per_sec, self._tokens + (now - self._last_refill) * self.bytes_per_sec)
            self._last_refill = now
            self._tokens -= nbytes
            deficit = -self._tokens
        if deficit > 0:
            self._sleep(deficit / self.bytes_per_sec)


@dataclass
class RetryPolicy:
    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0
    max_retry_after: float = 120.0

    def backoff(self, attempt: int, retry_after: float | None = None) -> float:
        """Delay before retry number `attempt` (1-based). `Retry-After` wins when the server sends it."""
        if retry_after is not None:
            return min(max(retry_after, 0.0), self.max_retry_after)
        exp = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        return random.uniform(exp / 2, exp)


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """`Retry-After` is either delta-seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    now = time.time() if now is None else now
    return max(0.0, dt.timestamp() - now)
