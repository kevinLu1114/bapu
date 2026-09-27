"""A small module whose tests the seed-red runner's own tests plant defects against."""


def discounted(price: float, percent: float) -> float:
    """``price`` reduced by ``percent``; the discount is capped at 50 percent."""
    if percent < 0:
        raise ValueError("percent must not be negative")
    if percent > 50:
        percent = 50
    return round(price * (100 - percent) / 100, 2)
