from app.ratelimit import SlidingWindowLimiter


def test_limit_and_window_expiry():
    now = [0.0]
    limiter = SlidingWindowLimiter(2, 10, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")  # separate key
    now[0] = 10.0
    assert limiter.allow("a")  # window passed


def test_reset():
    limiter = SlidingWindowLimiter(1, 60)
    assert limiter.allow("k") and not limiter.allow("k")
    limiter.reset()
    assert limiter.allow("k")
