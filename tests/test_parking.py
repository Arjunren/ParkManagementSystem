from datetime import datetime, timedelta

import pytest

from app.extensions import db
from app.models import ParkingSession, ParkingSlot, Payment, PaymentMethod, User, Vehicle, VehicleType, utcnow
from app.services.parking_service import ParkingError, check_in


def _ids(app):
    with app.app_context():
        return (
            VehicleType.query.filter_by(name="Sedan").one().id,
            ParkingSlot.query.filter_by(code="A-001").one().id,
            PaymentMethod.query.filter_by(name="Cash").one().id,
        )


def test_entry_and_exit_workflow(app, logged_attendant):
    vehicle_type_id, slot_id, method_id = _ids(app)
    response = logged_attendant.post("/parking/entry", data={
        "plate_number": "ABC 1234", "vehicle_type_id": vehicle_type_id, "slot_id": slot_id,
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Vehicle checked in" in response.data
    with app.app_context():
        session_id = ParkingSession.query.filter_by(status="ACTIVE").one().id
        assert db.session.get(ParkingSlot, slot_id).status == "OCCUPIED"
    response = logged_attendant.post(f"/parking/exit/{session_id}", data={
        "payment_method_id": method_id, "amount_paid": "50.00",
    }, follow_redirects=False)
    assert response.status_code == 302
    assert "/parking/receipt/" in response.headers["Location"]
    with app.app_context():
        session = db.session.get(ParkingSession, session_id)
        assert session.status == "COMPLETED"
        assert session.payment_status == "PAID"
        assert session.slot.status == "AVAILABLE"
        assert Payment.query.filter_by(parking_session_id=session_id).count() == 1


def test_duplicate_vehicle_active_session_is_rejected(app):
    with app.app_context():
        attendant = User.query.filter_by(username="attendant").one()
        vehicle_type = VehicleType.query.filter_by(name="Sedan").one()
        first = ParkingSlot.query.filter_by(code="A-001").one()
        second = ParkingSlot.query.filter_by(code="A-002").one()
        check_in(plate_number="DUP 100", vehicle_type_id=vehicle_type.id, slot_id=first.id, attendant=attendant)
        with pytest.raises(ParkingError, match="already has an active"):
            check_in(plate_number="DUP 100", vehicle_type_id=vehicle_type.id, slot_id=second.id, attendant=attendant)


def test_duplicate_slot_assignment_is_rejected(app):
    with app.app_context():
        attendant = User.query.filter_by(username="attendant").one()
        vehicle_type = VehicleType.query.filter_by(name="Sedan").one()
        slot = ParkingSlot.query.filter_by(code="A-001").one()
        check_in(plate_number="ONE 100", vehicle_type_id=vehicle_type.id, slot_id=slot.id, attendant=attendant)
        with pytest.raises(ParkingError, match="no longer available"):
            check_in(plate_number="TWO 200", vehicle_type_id=vehicle_type.id, slot_id=slot.id, attendant=attendant)


def test_underpayment_does_not_close_session(app, logged_attendant):
    vehicle_type_id, slot_id, method_id = _ids(app)
    logged_attendant.post("/parking/entry", data={
        "plate_number": "LOW 100", "vehicle_type_id": vehicle_type_id, "slot_id": slot_id,
    })
    with app.app_context():
        session_id = ParkingSession.query.filter_by(status="ACTIVE").one().id
        parking_session = db.session.get(ParkingSession, session_id)
        parking_session.entry_time = utcnow() - timedelta(hours=4)
        db.session.commit()
    response = logged_attendant.post(f"/parking/exit/{session_id}", data={
        "payment_method_id": method_id, "amount_paid": "0.00",
    }, follow_redirects=True)
    assert b"less than the amount due" in response.data
    with app.app_context():
        assert db.session.get(ParkingSession, session_id).status == "ACTIVE"
        assert db.session.get(ParkingSlot, slot_id).status == "OCCUPIED"
        assert Payment.query.count() == 0


def test_receipt_idor_is_blocked_for_customer(app, client):
    from tests.conftest import login
    vehicle_type_id, slot_id, method_id = _ids(app)
    login(client, "attendant")
    client.post("/parking/entry", data={
        "plate_number": "IDOR 100", "vehicle_type_id": vehicle_type_id, "slot_id": slot_id,
    })
    with app.app_context():
        session_id = ParkingSession.query.filter_by(status="ACTIVE").one().id
    client.post(f"/parking/exit/{session_id}", data={
        "payment_method_id": method_id, "amount_paid": "50.00",
    })
    with app.app_context():
        payment_id = Payment.query.one().id
    client.post("/auth/logout")
    login(client, "customer")
    assert client.get(f"/parking/receipt/{payment_id}").status_code == 403
