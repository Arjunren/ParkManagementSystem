from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models import utcnow
from app.services.pricing_service import PricingError, calculate_parking_fee


@pytest.fixture()
def rate():
    return SimpleNamespace(
        base_fee=Decimal("50"), base_duration_minutes=180,
        hourly_rate=Decimal("20"), daily_maximum=Decimal("500"),
        overnight_fee=Decimal("50"), lost_ticket_fee=Decimal("250"),
        grace_period_minutes=10, flat_rate=None,
    )


def test_grace_period_is_free(rate):
    start = datetime(2026, 1, 1, 10)
    assert calculate_parking_fee(start, start + timedelta(minutes=10), rate) == (Decimal("0.00"), 10)


def test_base_and_succeeding_hour_round_up(rate):
    start = datetime(2026, 1, 1, 10)
    fee, minutes = calculate_parking_fee(start, start + timedelta(minutes=181), rate)
    assert fee == Decimal("70.00")
    assert minutes == 181


def test_lost_ticket_fee_is_added(rate):
    start = datetime(2026, 1, 1, 10)
    fee, _ = calculate_parking_fee(start, start + timedelta(hours=1), rate, lost_ticket=True)
    assert fee == Decimal("300.00")


def test_invalid_time_is_rejected(rate):
    now = utcnow()
    with pytest.raises(PricingError):
        calculate_parking_fee(now, now - timedelta(minutes=1), rate)
