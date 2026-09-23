from datetime import datetime, timezone
from decimal import Decimal

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30), unique=True, nullable=False)
    description = db.Column(db.String(255))


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False, index=True)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime)
    session_version = db.Column(db.Integer, nullable=False, default=1)
    last_login_at = db.Column(db.DateTime)
    deleted_at = db.Column(db.DateTime)
    role = db.relationship("Role", lazy="joined")

    @property
    def is_active(self):
        return self.is_enabled and self.deleted_at is None

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_role(self, *roles):
        return bool(self.role and self.role.name in roles)


class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_tokens"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    user = db.relationship("User")


class ParkingArea(TimestampMixin, db.Model):
    __tablename__ = "parking_areas"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(500))
    location = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default="ACTIVE")
    archived_at = db.Column(db.DateTime)
    slots = db.relationship("ParkingSlot", back_populates="area", lazy="dynamic")
    __table_args__ = (CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_area_status"),)


class VehicleType(TimestampMixin, db.Model):
    __tablename__ = "vehicle_types"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    description = db.Column(db.String(255))
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)


class ParkingSlot(TimestampMixin, db.Model):
    __tablename__ = "parking_slots"
    id = db.Column(db.Integer, primary_key=True)
    area_id = db.Column(db.Integer, db.ForeignKey("parking_areas.id"), nullable=False, index=True)
    code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    slot_type = db.Column(db.String(30), nullable=False, default="STANDARD")
    allowed_vehicle_type_id = db.Column(db.Integer, db.ForeignKey("vehicle_types.id"), index=True)
    status = db.Column(db.String(20), nullable=False, default="AVAILABLE", index=True)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)
    area = db.relationship("ParkingArea", back_populates="slots", lazy="joined")
    allowed_vehicle_type = db.relationship("VehicleType")
    __table_args__ = (
        CheckConstraint(
            "status IN ('AVAILABLE','OCCUPIED','RESERVED','MAINTENANCE','DISABLED')",
            name="ck_slot_status",
        ),
    )


class ParkingRate(TimestampMixin, db.Model):
    __tablename__ = "parking_rates"
    id = db.Column(db.Integer, primary_key=True)
    vehicle_type_id = db.Column(db.Integer, db.ForeignKey("vehicle_types.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    base_fee = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("0"))
    base_duration_minutes = db.Column(db.Integer, nullable=False, default=180)
    hourly_rate = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("0"))
    daily_maximum = db.Column(db.Numeric(10, 2))
    overnight_fee = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("0"))
    lost_ticket_fee = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("0"))
    grace_period_minutes = db.Column(db.Integer, nullable=False, default=10)
    flat_rate = db.Column(db.Numeric(10, 2))
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    effective_from = db.Column(db.DateTime, nullable=False, default=utcnow)
    effective_until = db.Column(db.DateTime)
    vehicle_type = db.relationship("VehicleType", lazy="joined")
    __table_args__ = (
        CheckConstraint("base_fee >= 0 AND hourly_rate >= 0", name="ck_rate_nonnegative"),
        CheckConstraint("base_duration_minutes > 0 AND grace_period_minutes >= 0", name="ck_rate_minutes"),
    )


class Vehicle(TimestampMixin, db.Model):
    __tablename__ = "vehicles"
    id = db.Column(db.Integer, primary_key=True)
    plate_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    vehicle_type_id = db.Column(db.Integer, db.ForeignKey("vehicle_types.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    owner_name = db.Column(db.String(120))
    contact = db.Column(db.String(100))
    vehicle_type = db.relationship("VehicleType", lazy="joined")
    customer = db.relationship("User")


class ParkingSession(TimestampMixin, db.Model):
    __tablename__ = "parking_sessions"
    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=False, index=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("parking_slots.id"), nullable=False, index=True)
    attendant_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    parking_rate_id = db.Column(db.Integer, db.ForeignKey("parking_rates.id"), nullable=False, index=True)
    entry_time = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    exit_time = db.Column(db.DateTime, index=True)
    duration_minutes = db.Column(db.Integer)
    amount_due = db.Column(db.Numeric(10, 2))
    status = db.Column(db.String(20), nullable=False, default="ACTIVE", index=True)
    payment_status = db.Column(db.String(20), nullable=False, default="UNPAID", index=True)
    notes = db.Column(db.String(500))
    vehicle = db.relationship("Vehicle", lazy="joined")
    slot = db.relationship("ParkingSlot", lazy="joined")
    attendant = db.relationship("User", lazy="joined")
    parking_rate = db.relationship("ParkingRate", lazy="joined")
    payment = db.relationship("Payment", back_populates="parking_session", uselist=False)
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','PAYMENT_PENDING','COMPLETED','CANCELLED')", name="ck_session_status"),
        CheckConstraint("payment_status IN ('UNPAID','PAID','VOID')", name="ck_payment_status"),
        Index("ix_session_vehicle_status", "vehicle_id", "status"),
        Index("ix_session_slot_status", "slot_id", "status"),
    )


class PaymentMethod(TimestampMixin, db.Model):
    __tablename__ = "payment_methods"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    receipt_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    parking_session_id = db.Column(db.Integer, db.ForeignKey("parking_sessions.id"), unique=True, nullable=False)
    amount_due = db.Column(db.Numeric(10, 2), nullable=False)
    amount_paid = db.Column(db.Numeric(10, 2), nullable=False)
    change_amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method_id = db.Column(db.Integer, db.ForeignKey("payment_methods.id"), nullable=False, index=True)
    payment_reference = db.Column(db.String(100))
    processed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    paid_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    status = db.Column(db.String(20), nullable=False, default="COMPLETED")
    parking_session = db.relationship("ParkingSession", back_populates="payment")
    payment_method = db.relationship("PaymentMethod", lazy="joined")
    processed_by = db.relationship("User", lazy="joined")
    __table_args__ = (
        CheckConstraint("amount_due >= 0 AND amount_paid >= amount_due AND change_amount >= 0", name="ck_payment_amounts"),
    )


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    username = db.Column(db.String(50))
    action = db.Column(db.String(80), nullable=False, index=True)
    resource = db.Column(db.String(80), nullable=False, index=True)
    resource_id = db.Column(db.String(80))
    ip_address = db.Column(db.String(45))
    metadata_json = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    user = db.relationship("User")


class SystemSetting(TimestampMixin, db.Model):
    __tablename__ = "system_settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    description = db.Column(db.String(255))
    is_public = db.Column(db.Boolean, nullable=False, default=False)
