import secrets
from datetime import datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    ParkingSession, ParkingSlot, Payment, PaymentMethod, Vehicle, VehicleType, utcnow,
)
from app.security.validators import normalize_plate
from app.services.audit_service import record_audit
from app.services.pricing_service import PricingError, active_rate_for, calculate_parking_fee


class ParkingError(ValueError):
    pass


def _reference(prefix):
    return f"{prefix}-{utcnow():%Y%m%d}-{secrets.token_hex(4).upper()}"


def check_in(*, plate_number, vehicle_type_id, slot_id, attendant, owner_name=None, contact=None, notes=None):
    plate = normalize_plate(plate_number)
    try:
        slot = ParkingSlot.query.filter_by(id=slot_id).with_for_update().first()
        if not slot or not slot.is_enabled:
            raise ParkingError("The selected parking slot does not exist or is disabled.")
        if slot.status != "AVAILABLE":
            raise ParkingError("The selected parking slot is no longer available.")
        vehicle_type = db.session.get(VehicleType, vehicle_type_id)
        if not vehicle_type or not vehicle_type.is_enabled:
            raise ParkingError("The selected vehicle type is unavailable.")
        if slot.allowed_vehicle_type_id and slot.allowed_vehicle_type_id != vehicle_type.id:
            raise ParkingError("This vehicle type is not allowed in the selected slot.")

        rate = active_rate_for(vehicle_type.id)
        if not rate:
            raise ParkingError("No active parking rate is configured for this vehicle type.")

        vehicle = Vehicle.query.filter_by(plate_number=plate).with_for_update().first()
        if vehicle:
            active = (
                ParkingSession.query.filter_by(vehicle_id=vehicle.id, status="ACTIVE")
                .with_for_update().first()
            )
            if active:
                raise ParkingError("This vehicle already has an active parking session.")
            vehicle.vehicle_type_id = vehicle_type.id
            vehicle.owner_name = owner_name or vehicle.owner_name
            vehicle.contact = contact or vehicle.contact
        else:
            vehicle = Vehicle(
                plate_number=plate, vehicle_type=vehicle_type,
                owner_name=owner_name or None, contact=contact or None,
            )
            db.session.add(vehicle)
            db.session.flush()

        parking_session = ParkingSession(
            ticket_number=_reference("PK"), vehicle=vehicle, slot=slot,
            attendant=attendant, parking_rate=rate, notes=notes or None,
        )
        slot.status = "OCCUPIED"
        db.session.add(parking_session)
        db.session.flush()
        record_audit("VEHICLE_ENTRY", "parking_session", parking_session.id, {
            "ticket_number": parking_session.ticket_number, "plate_number": plate, "slot": slot.code,
        }, user=attendant)
        db.session.commit()
        return parking_session
    except (ParkingError, IntegrityError):
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        raise


def quote_exit(parking_session, at_time=None, lost_ticket=False):
    if parking_session.status != "ACTIVE":
        raise ParkingError("Only active parking sessions can be checked out.")
    exit_time = at_time or utcnow()
    rate = parking_session.parking_rate
    try:
        amount, minutes = calculate_parking_fee(parking_session.entry_time, exit_time, rate, lost_ticket)
    except PricingError as exc:
        raise ParkingError(str(exc)) from exc
    return amount, minutes, exit_time


def complete_exit(*, session_id, payment_method_id, amount_paid, attendant, payment_reference=None, lost_ticket=False):
    try:
        parking_session = ParkingSession.query.filter_by(id=session_id).with_for_update().first()
        if not parking_session or parking_session.status != "ACTIVE":
            raise ParkingError("This parking session is no longer active.")
        slot = ParkingSlot.query.filter_by(id=parking_session.slot_id).with_for_update().first()
        method = db.session.get(PaymentMethod, payment_method_id)
        if not method or not method.is_enabled:
            raise ParkingError("Select a valid payment method.")
        due, minutes, exit_time = quote_exit(parking_session, lost_ticket=lost_ticket)
        paid = Decimal(amount_paid).quantize(Decimal("0.01"))
        if paid < due:
            raise ParkingError("Amount paid cannot be less than the amount due.")

        payment = Payment(
            receipt_number=_reference("RCPT"), parking_session=parking_session,
            amount_due=due, amount_paid=paid, change_amount=paid - due,
            payment_method=method, payment_reference=(payment_reference or None),
            processed_by=attendant,
        )
        parking_session.exit_time = exit_time
        parking_session.duration_minutes = minutes
        parking_session.amount_due = due
        parking_session.payment_status = "PAID"
        parking_session.status = "COMPLETED"
        slot.status = "AVAILABLE"
        db.session.add(payment)
        db.session.flush()
        record_audit("PAYMENT_CREATED", "payment", payment.id, {
            "receipt_number": payment.receipt_number, "amount_due": str(due),
        }, user=attendant)
        record_audit("VEHICLE_EXIT", "parking_session", parking_session.id, {
            "ticket_number": parking_session.ticket_number, "slot": slot.code,
        }, user=attendant)
        db.session.commit()
        return payment
    except (ParkingError, IntegrityError, ArithmeticError):
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        raise
