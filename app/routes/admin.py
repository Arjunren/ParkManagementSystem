from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.models import (
    AuditLog, ParkingArea, ParkingRate, ParkingSlot, Payment, PaymentMethod,
    Role, SystemSetting, User, VehicleType, utcnow,
)
from app.security.decorators import role_required
from app.security.validators import USERNAME_RE, normalize_email, parse_money, validate_password, validate_slot_code
from app.services.audit_service import record_audit


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
@admin_bp.route("/areas", methods=["GET", "POST"])
@login_required
@role_required("admin")
def areas():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        if not name or ParkingArea.query.filter_by(name=name).first():
            flash("Area name is required and must be unique.", "error")
        else:
            area = ParkingArea(
                name=name, description=request.form.get("description", "").strip()[:500],
                location=request.form.get("location", "").strip()[:255],
            )
            db.session.add(area)
            db.session.flush()
            record_audit("AREA_CREATED", "parking_area", area.id, {"name": name})
            db.session.commit()
            flash("Parking area created.", "success")
            return redirect(url_for("admin.areas"))
    return render_template("admin/areas.html", areas=ParkingArea.query.order_by(ParkingArea.name).all())


@admin_bp.post("/areas/<int:area_id>/status")
@login_required
@role_required("admin")
def area_status(area_id):
    area = db.get_or_404(ParkingArea, area_id)
    status = request.form.get("status", "").upper()
    if status not in {"ACTIVE", "INACTIVE"}:
        flash("Invalid area status.", "error")
    else:
        area.status = status
        record_audit("AREA_UPDATED", "parking_area", area.id, {"status": status})
        db.session.commit()
        flash("Area status updated.", "success")
    return redirect(url_for("admin.areas"))


@admin_bp.route("/slots", methods=["GET", "POST"])
@login_required
@role_required("admin")
def slots():
    areas_list = ParkingArea.query.filter_by(status="ACTIVE").order_by(ParkingArea.name).all()
    types = VehicleType.query.filter_by(is_enabled=True).order_by(VehicleType.name).all()
    if request.method == "POST":
        code = validate_slot_code(request.form.get("code"))
        if not code or ParkingSlot.query.filter_by(code=code).first():
            flash("Slot code is invalid or already exists.", "error")
        else:
            try:
                allowed = request.form.get("allowed_vehicle_type_id", type=int)
                slot = ParkingSlot(
                    code=code, area_id=int(request.form.get("area_id", 0)),
                    slot_type=request.form.get("slot_type", "STANDARD").strip().upper()[:30],
                    allowed_vehicle_type_id=allowed or None,
                )
                db.session.add(slot)
                db.session.flush()
                record_audit("SLOT_CREATED", "parking_slot", slot.id, {"code": code})
                db.session.commit()
                flash("Parking slot created.", "success")
                return redirect(url_for("admin.slots"))
            except Exception:
                db.session.rollback()
                flash("Select a valid parking area and vehicle type.", "error")
    page = ParkingSlot.query.order_by(ParkingSlot.code).paginate(
        page=request.args.get("page", 1, type=int), per_page=30, error_out=False
    )
    return render_template("admin/slots.html", page=page, areas=areas_list, vehicle_types=types)


@admin_bp.post("/slots/<int:slot_id>/status")
@login_required
@role_required("admin")
def slot_status(slot_id):
    slot = db.get_or_404(ParkingSlot, slot_id)
    status = request.form.get("status", "").upper()
    allowed = {"AVAILABLE", "RESERVED", "MAINTENANCE", "DISABLED"}
    if slot.status == "OCCUPIED" or status not in allowed:
        flash("Occupied slots cannot be changed manually, or the selected status is invalid.", "error")
    else:
        slot.status = status
        record_audit("SLOT_STATUS_CHANGED", "parking_slot", slot.id, {"status": status})
        db.session.commit()
        flash("Slot status updated.", "success")
    return redirect(url_for("admin.slots"))


@admin_bp.route("/vehicle-types", methods=["GET", "POST"])
@login_required
@role_required("admin")
def vehicle_types():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:60]
        if not name or VehicleType.query.filter_by(name=name).first():
            flash("Vehicle type name is required and must be unique.", "error")
        else:
            item = VehicleType(name=name, description=request.form.get("description", "").strip()[:255])
            db.session.add(item)
            db.session.flush()
            record_audit("VEHICLE_TYPE_CREATED", "vehicle_type", item.id, {"name": name})
            db.session.commit()
            flash("Vehicle type created.", "success")
            return redirect(url_for("admin.vehicle_types"))
    return render_template("admin/vehicle_types.html", items=VehicleType.query.order_by(VehicleType.name).all())


@admin_bp.post("/vehicle-types/<int:item_id>/toggle")
@login_required
@role_required("admin")
def vehicle_type_toggle(item_id):
    item = db.get_or_404(VehicleType, item_id)
    item.is_enabled = not item.is_enabled
    record_audit("VEHICLE_TYPE_UPDATED", "vehicle_type", item.id, {"enabled": item.is_enabled})
    db.session.commit()
    flash("Vehicle type updated.", "success")
    return redirect(url_for("admin.vehicle_types"))


@admin_bp.route("/rates", methods=["GET", "POST"])
@login_required
@role_required("admin")
def rates():
    types = VehicleType.query.filter_by(is_enabled=True).order_by(VehicleType.name).all()
    if request.method == "POST":
        fields = {key: parse_money(request.form.get(key)) for key in (
            "base_fee", "hourly_rate", "overnight_fee", "lost_ticket_fee"
        )}
        optional = {key: parse_money(request.form.get(key)) if request.form.get(key) else None for key in (
            "daily_maximum", "flat_rate"
        )}
        if any(value is None for value in fields.values()):
            flash("Rate amounts must be valid non-negative numbers.", "error")
        else:
            try:
                vehicle_type_id = int(request.form.get("vehicle_type_id", 0))
                ParkingRate.query.filter_by(vehicle_type_id=vehicle_type_id, is_active=True).update(
                    {"is_active": False, "effective_until": utcnow()}
                )
                rate = ParkingRate(
                    vehicle_type_id=vehicle_type_id, name=request.form.get("name", "Standard")[:100],
                    base_duration_minutes=max(1, int(request.form.get("base_duration_minutes", 180))),
                    grace_period_minutes=max(0, int(request.form.get("grace_period_minutes", 10))),
                    **fields, **optional,
                )
                db.session.add(rate)
                db.session.flush()
                record_audit("PARKING_RATE_CREATED", "parking_rate", rate.id, {
                    "vehicle_type_id": vehicle_type_id, "name": rate.name,
                })
                db.session.commit()
                flash("New rate version activated.", "success")
                return redirect(url_for("admin.rates"))
            except Exception:
                db.session.rollback()
                flash("Check all rate fields and select a valid vehicle type.", "error")
    return render_template(
        "admin/rates.html", vehicle_types=types,
        rates=ParkingRate.query.order_by(ParkingRate.is_active.desc(), ParkingRate.effective_from.desc()).all(),
    )


@admin_bp.route("/payment-methods", methods=["GET", "POST"])
@login_required
@role_required("admin")
def payment_methods():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:50]
        if name and not PaymentMethod.query.filter_by(name=name).first():
            item = PaymentMethod(name=name)
            db.session.add(item)
            db.session.flush()
            record_audit("PAYMENT_METHOD_CREATED", "payment_method", item.id, {"name": name})
            db.session.commit()
            flash("Payment method created.", "success")
            return redirect(url_for("admin.payment_methods"))
        flash("Payment method name is required and must be unique.", "error")
    return render_template("admin/payment_methods.html", items=PaymentMethod.query.order_by(PaymentMethod.name).all())


@admin_bp.post("/payment-methods/<int:item_id>/toggle")
@login_required
@role_required("admin")
def payment_method_toggle(item_id):
    item = db.get_or_404(PaymentMethod, item_id)
    item.is_enabled = not item.is_enabled
    record_audit("PAYMENT_METHOD_UPDATED", "payment_method", item.id, {"enabled": item.is_enabled})
    db.session.commit()
    return redirect(url_for("admin.payment_methods"))


@admin_bp.route("/users", methods=["GET", "POST"])
@login_required
@role_required("admin")
@limiter.limit("10 per hour", methods=["POST"])
def users():
    roles = Role.query.order_by(Role.name).all()
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        email = normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        error = validate_password(password, current_app.config["PASSWORD_MIN_LENGTH"])
        if not USERNAME_RE.fullmatch(username) or not email:
            error = "Enter a valid username and email address."
        elif User.query.filter((User.username == username) | (User.email == email)).first():
            error = "That username or email is already in use."
        if error:
            flash(error, "error")
        else:
            role = db.session.get(Role, request.form.get("role_id", type=int))
            if not role:
                flash("Select a valid role.", "error")
            else:
                user = User(username=username, email=email, role=role, full_name=request.form.get("full_name", "")[:120])
                user.set_password(password)
                db.session.add(user)
                db.session.flush()
                record_audit("USER_CREATED", "user", user.id, {"role": role.name})
                db.session.commit()
                flash("User created.", "success")
                return redirect(url_for("admin.users"))
    page = User.query.filter(User.deleted_at.is_(None)).order_by(User.username).paginate(
        page=request.args.get("page", 1, type=int), per_page=25, error_out=False
    )
    return render_template("admin/users.html", page=page, roles=roles)


@admin_bp.post("/users/<int:user_id>/update")
@login_required
@role_required("admin")
def user_update(user_id):
    user = db.get_or_404(User, user_id)
    role = db.session.get(Role, request.form.get("role_id", type=int))
    enabled = request.form.get("is_enabled") == "on"
    if user.id == current_user.id and (not enabled or not role or role.name != "admin"):
        flash("You cannot disable or demote your own administrator account.", "error")
    elif not role:
        flash("Select a valid role.", "error")
    else:
        changed = user.role_id != role.id or user.is_enabled != enabled
        user.role = role
        user.is_enabled = enabled
        if changed:
            user.session_version += 1
        record_audit("USER_UPDATED", "user", user.id, {"role": role.name, "enabled": enabled})
        db.session.commit()
        flash("User updated.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.get("/payments")
@login_required
@role_required("admin")
def payments():
    page = Payment.query.order_by(Payment.paid_at.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=25, error_out=False
    )
    return render_template("admin/payments.html", page=page)


@admin_bp.get("/audit-logs")
@login_required
@role_required("admin")
def audit_logs():
    action = request.args.get("action", "").strip()[:80]
    query = AuditLog.query
    if action:
        query = query.filter(AuditLog.action == action)
    page = query.order_by(AuditLog.created_at.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=30, error_out=False
    )
    return render_template("admin/audit_logs.html", page=page, action=action)


@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
@role_required("admin")
def settings():
    if request.method == "POST":
        key = request.form.get("key", "").strip().lower()[:100]
        value = request.form.get("value", "").strip()[:2000]
        if not key.replace("_", "").isalnum():
            flash("Setting keys may contain only letters, numbers, and underscores.", "error")
        else:
            setting = SystemSetting.query.filter_by(key=key).first() or SystemSetting(key=key)
            setting.value = value
            setting.description = request.form.get("description", "").strip()[:255]
            db.session.add(setting)
            db.session.flush()
            record_audit("SETTING_UPDATED", "system_setting", setting.id, {"key": key})
            db.session.commit()
            flash("Setting saved.", "success")
            return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", items=SystemSetting.query.order_by(SystemSetting.key).all())
