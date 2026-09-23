from datetime import datetime
from decimal import Decimal

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    ParkingArea, ParkingRate, ParkingSlot, PaymentMethod, Role, User, VehicleType,
)


@pytest.fixture()
def app():
    application = create_app("testing")
    with application.app_context():
        db.create_all()
        roles = {name: Role(name=name, description=name.title()) for name in ("admin", "attendant", "customer")}
        db.session.add_all(roles.values())
        users = []
        for username, role in (("admin", "admin"), ("attendant", "attendant"), ("customer", "customer")):
            user = User(
                username=username, email=f"{username}@example.com", role=roles[role],
                full_name=username.title(),
            )
            user.set_password("ValidPass1!")
            users.append(user)
        vehicle_type = VehicleType(name="Sedan")
        area = ParkingArea(name="Ground Floor", location="Building A")
        db.session.add_all([*users, vehicle_type, area])
        db.session.flush()
        slot = ParkingSlot(area=area, code="A-001", allowed_vehicle_type=vehicle_type)
        second_slot = ParkingSlot(area=area, code="A-002", allowed_vehicle_type=vehicle_type)
        rate = ParkingRate(
            vehicle_type=vehicle_type, name="Standard", base_fee=Decimal("50.00"),
            base_duration_minutes=180, hourly_rate=Decimal("20.00"),
            daily_maximum=Decimal("500.00"), overnight_fee=Decimal("50.00"),
            lost_ticket_fee=Decimal("250.00"), grace_period_minutes=10,
            effective_from=datetime(2020, 1, 1),
        )
        method = PaymentMethod(name="Cash")
        db.session.add_all([slot, second_slot, rate, method])
        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, username="admin", password="ValidPass1!"):
    return client.post("/auth/login", data={"identity": username, "password": password}, follow_redirects=False)


@pytest.fixture()
def logged_admin(client):
    login(client)
    return client


@pytest.fixture()
def logged_attendant(client):
    login(client, "attendant")
    return client
