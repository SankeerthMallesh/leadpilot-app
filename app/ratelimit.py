"""In-process sliding-window rate limiter (a Redis-backed one arrives with the job queue)."""
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

_registry: list["SlidingWindowLimiter"] = []


class SlidingWindowLimiter:
    """Allow at most max_events per key within window_seconds."""

    def __init__(
        self, max_events: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        _registry.append(self)

    def allow(self, key: str) -> bool:
        """Record and allow the event, or return False when the limit is reached."""
        now = self._clock()
        with self._lock:
            queue = self._events[key]
            while queue and now - queue[0] >= self.window:
                queue.popleft()
            if len(queue) >= self.max_events:
                return False
            queue.append(now)
            if len(self._events) > 5000:
                for stale in [k for k, q in self._events.items() if not q]:
                    del self._events[stale]
            return True

    def reset(self) -> None:
        """Forget all events (used by tests)."""
        with self._lock:
            self._events.clear()


def reset_all() -> None:
    """Reset every limiter."""
    for limiter in _registry:
        limiter.reset()
