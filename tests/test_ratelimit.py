from email.utils import format_datetime
from datetime import datetime, timezone

import pytest

from sc_memories_downloader.ratelimit import RateLimiter, RetryPolicy, parse_retry_after


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_min_gap_spaces_requests():
    clock = FakeClock()
    rl = RateLimiter(min_gap=0.25, clock=clock, sleep=clock.sleep)
    for _ in range(4):
        rl.before_request()
    assert clock.slept == pytest.approx([0.25, 0.25, 0.25])


def test_min_gap_zero_never_sleeps():
    clock = FakeClock()
    rl = RateLimiter(min_gap=0, clock=clock, sleep=clock.sleep)
    rl.before_request()
    rl.before_request()
    assert clock.slept == []


def test_token_bucket_holds_rate():
    clock = FakeClock()
    rl = RateLimiter(bytes_per_sec=1000, clock=clock, sleep=clock.sleep)
    rl.consume(1000)  # the initial burst is free
    assert clock.slept == []
    rl.consume(500)
    assert clock.slept == pytest.approx([0.5])
    rl.consume(0)
    assert len(clock.slept) == 1


def test_unlimited_rate_never_sleeps():
    clock = FakeClock()
    rl = RateLimiter.from_settings(0, 0)
    rl._sleep = clock.sleep
    rl.consume(10**9)
    assert clock.slept == []


def test_from_settings_units():
    rl = RateLimiter.from_settings(2.0, 250)
    assert rl.bytes_per_sec == 2 * 1024 * 1024
    assert rl.min_gap == 0.25


def test_backoff_is_bounded_and_grows():
    p = RetryPolicy(base_delay=1, max_delay=8)
    for attempt, cap in [(1, 1), (2, 2), (3, 4), (4, 8), (10, 8)]:
        for _ in range(20):
            d = p.backoff(attempt)
            assert cap / 2 <= d <= cap


def test_retry_after_wins_and_is_capped():
    p = RetryPolicy(max_retry_after=120)
    assert p.backoff(1, retry_after=7) == 7
    assert p.backoff(1, retry_after=10_000) == 120
    assert p.backoff(1, retry_after=-3) == 0


def test_parse_retry_after():
    assert parse_retry_after("15") == 15.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("soon") is None
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    later = format_datetime(datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc), usegmt=True)
    assert parse_retry_after(later, now=now.timestamp()) == pytest.approx(30)
    earlier = format_datetime(datetime(2025, 1, 1, tzinfo=timezone.utc), usegmt=True)
    assert parse_retry_after(earlier, now=now.timestamp()) == 0
