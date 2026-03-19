import queue


def post_event(q: queue.Queue, event_type: str, **payload) -> None:
    """Push a typed event into the UI queue."""
    q.put({"type": event_type, **payload})

