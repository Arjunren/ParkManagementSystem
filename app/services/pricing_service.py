import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from app.models import ParkingRate, utcnow


class PricingError(ValueError):
    pass


def active_rate_for(vehicle_type_id, at_time=None):
    moment = at_time or utcnow()
    return (
        ParkingRate.query.filter(
            ParkingRate.vehicle_type_id == vehicle_type_id,
            ParkingRate.is_active.is_(True),
            ParkingRate.effective_from <= moment,
            (ParkingRate.effective_until.is_(None) | (ParkingRate.effective_until > moment)),
        )
        .order_by(ParkingRate.effective_from.desc())
        .first()
    )


def calculate_parking_fee(entry_time, exit_time, rate, lost_ticket=False):
    if not rate:
        raise PricingError("No active parking rate is configured for this vehicle type.")
    if exit_time < entry_time:
        raise PricingError("Exit time cannot be earlier than entry time.")
    minutes = max(0, math.ceil((exit_time - entry_time).total_seconds() / 60))
    if minutes <= rate.grace_period_minutes:
        charge = Decimal("0")
    elif rate.flat_rate is not None:
        charge = Decimal(rate.flat_rate)
    else:
        billable = max(0, minutes - rate.base_duration_minutes)
        extra_hours = math.ceil(billable / 60)
        charge = Decimal(rate.base_fee) + Decimal(rate.hourly_rate) * extra_hours
        if rate.daily_maximum is not None:
            days = max(1, math.ceil(minutes / 1440))
            charge = min(charge, Decimal(rate.daily_maximum) * days)
        if minutes > 1440 and rate.overnight_fee:
            charge += Decimal(rate.overnight_fee) * math.floor(minutes / 1440)
    if lost_ticket:
        charge += Decimal(rate.lost_ticket_fee)
    return charge.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), minutes
