"""
Backend -> UI event channel.

Worker threads only ever call `post_event`; the UI drains the queue on its own
loop. Event types and payloads:

- log(message)
- phase(text)
- overall(percent)
- item_added(id, title, kind)
- item_progress(id, percent, bytes, total_bytes, rate_mb_s, done_count?, total_count?)
- item_state(id, state, detail)        state: queued|running|paused|stopped|done|failed|expired|skipped
- links_found(urls)
- auth_state(state, detail)            state: idle|running|done|failed
- done(message, ok)
- error(message)
"""

import queue
import threading
import time


def post_event(q: queue.Queue, event_type: str, **payload) -> None:
    """Push a typed event into the UI queue."""
    q.put({"type": event_type, **payload})


class EventThrottle:
    """Lets a given key through at most once per `interval` seconds."""

    def __init__(self, interval: float = 0.25) -> None:
        self.interval = interval
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def ready(self, key: str, force: bool = False) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key)
            if force or last is None or now - last >= self.interval:
                self._last[key] = now
                return True
            return False
