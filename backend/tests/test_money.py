from decimal import Decimal

from app.utils.money import (
    calculate_percentage,
    format_inr,
    paise_to_rupees,
    rupees_to_paise,
)


def test_rupees_to_paise_integer():
    assert rupees_to_paise(299) == 29900
    assert rupees_to_paise(2499) == 249900
    assert rupees_to_paise("2499.50") == 249950


def test_paise_to_rupees():
    assert paise_to_rupees(249900) == Decimal("2499.00")


def test_format_inr_indian_grouping():
    assert format_inr(249900) == "₹2,499.00"
    assert format_inr(10000000) == "₹1,00,000.00"
    assert format_inr(39900) == "₹399.00"


def test_calculate_percentage_is_integer_paise():
    # 20% of ₹2,499 -> ₹499.80 -> 49980 paise
    assert calculate_percentage(249900, 20) == 49980
    assert isinstance(calculate_percentage(249900, 20), int)
