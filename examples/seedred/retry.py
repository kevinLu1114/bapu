"""Delays between retries: exponential backoff with a cap."""


def backoff_delays(attempts: int, base: float = 1.0, cap: float = 30.0) -> list:
    """The delay before each retry: base, 2 * base, 4 * base, ..., never above ``cap``."""
    if attempts < 0:
        raise ValueError("attempts must not be negative")
    delays = []
    for attempt in range(attempts):
        delay = base * (2**attempt)
        if delay > cap:
            delay = cap
        delays.append(delay)
    return delays
