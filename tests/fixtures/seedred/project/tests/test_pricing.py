import pytest
from pricing import discounted


def test_discount_is_applied():
    assert discounted(200.0, 10) == 180.0


def test_discount_is_capped_at_fifty_percent():
    assert discounted(200.0, 80) == 100.0


def test_negative_discount_is_refused():
    with pytest.raises(ValueError):
        discounted(100.0, -5)
