import pytest
from retry import backoff_delays


def test_delays_double_each_attempt():
    assert backoff_delays(3, base=1.0) == [1.0, 2.0, 4.0]


def test_delays_never_exceed_the_cap():
    assert backoff_delays(6, base=1.0, cap=10.0) == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]


def test_negative_attempts_are_refused():
    with pytest.raises(ValueError):
        backoff_delays(-1)
