from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db, limiter
from app.models import ParkingArea, ParkingSession, ParkingSlot, Payment, PaymentMethod, Vehicle, VehicleType
from app.security.decorators import role_required
from app.security.validators import parse_money, validate_plate
from app.services.parking_service import ParkingError, check_in, complete_exit, quote_exit


parking_bp = Blueprint("parking", __name__, url_prefix="/parking")


@parking_bp.route("/entry", methods=["GET", "POST"])
@login_required
@role_required("admin", "attendant")
@limiter.limit("30 per minute", methods=["POST"])
def entry():
    types = VehicleType.query.filter_by(is_enabled=True).order_by(VehicleType.name).all()
    slots = ParkingSlot.query.filter_by(status="AVAILABLE", is_enabled=True).order_by(ParkingSlot.code).all()
    if request.method == "POST":
        plate = validate_plate(request.form.get("plate_number"))
        if not plate:
            flash("Enter a valid plate number.", "error")
        else:
            try:
                parking_session = check_in(
                    plate_number=plate, vehicle_type_id=int(request.form.get("vehicle_type_id", 0)),
                    slot_id=int(request.form.get("slot_id", 0)), attendant=current_user,
                    owner_name=request.form.get("owner_name", "").strip()[:120],
                    contact=request.form.get("contact", "").strip()[:100],
                    notes=request.form.get("notes", "").strip()[:500],
                )
                flash(f"Vehicle checked in. Ticket {parking_session.ticket_number}", "success")
                return redirect(url_for("parking.active"))
            except (ParkingError, ValueError) as exc:
                flash(str(exc), "error")
    return render_template("parking/entry.html", vehicle_types=types, slots=slots)


@parking_bp.get("/active")
@login_required
@role_required("admin", "attendant")
def active():
    query = ParkingSession.query.filter_by(status="ACTIVE")
    search = request.args.get("q", "").strip()
    if search:
        term = f"%{search[:40]}%"
        query = query.join(Vehicle).join(ParkingSlot).filter(or_(
            ParkingSession.ticket_number.like(term), Vehicle.plate_number.like(term), ParkingSlot.code.like(term)
        ))
    page = query.order_by(ParkingSession.entry_time.asc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=20, error_out=False
    )
    return render_template("parking/active.html", page=page, search=search)


@parking_bp.route("/exit/<int:session_id>", methods=["GET", "POST"])
@login_required
@role_required("admin", "attendant")
@limiter.limit("20 per minute", methods=["POST"])
def exit_vehicle(session_id):
    parking_session = ParkingSession.query.filter_by(id=session_id, status="ACTIVE").first_or_404()
    methods = PaymentMethod.query.filter_by(is_enabled=True).order_by(PaymentMethod.name).all()
    try:
        due, minutes, quoted_at = quote_exit(parking_session, lost_ticket=request.form.get("lost_ticket") == "on")
    except ParkingError as exc:
        flash(str(exc), "error")
        return redirect(url_for("parking.active"))
    if request.method == "POST":
        paid = parse_money(request.form.get("amount_paid"))
        if paid is None:
            flash("Enter a valid payment amount.", "error")
        else:
            try:
                payment = complete_exit(
                    session_id=session_id, payment_method_id=int(request.form.get("payment_method_id", 0)),
                    amount_paid=paid, attendant=current_user,
                    payment_reference=request.form.get("payment_reference", "").strip()[:100],
                    lost_ticket=request.form.get("lost_ticket") == "on",
                )
                flash("Payment recorded and parking session completed.", "success")
                return redirect(url_for("parking.receipt", payment_id=payment.id))
            except (ParkingError, ValueError, ArithmeticError) as exc:
                flash(str(exc), "error")
    return render_template(
        "parking/exit.html", parking_session=parking_session, due=due,
        duration_minutes=minutes, quoted_at=quoted_at, payment_methods=methods,
    )


@parking_bp.get("/history")
@login_required
def history():
    query = ParkingSession.query
    if current_user.has_role("customer"):
        query = query.join(Vehicle).filter(Vehicle.customer_id == current_user.id)
    elif not current_user.has_role("admin", "attendant"):
        abort(403)
    status = request.args.get("status", "").upper()
    if status in {"ACTIVE", "COMPLETED", "CANCELLED"}:
        query = query.filter(ParkingSession.status == status)
    vehicle_type_id = request.args.get("vehicle_type_id", type=int)
    area_id = request.args.get("area_id", type=int)
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    if vehicle_type_id:
        query = query.filter(ParkingSession.vehicle.has(vehicle_type_id=vehicle_type_id))
    if area_id:
        query = query.filter(ParkingSession.slot.has(area_id=area_id))
    try:
        if start:
            query = query.filter(ParkingSession.entry_time >= datetime.strptime(start, "%Y-%m-%d"))
        if end:
            query = query.filter(ParkingSession.entry_time < datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1))
    except ValueError:
        flash("Invalid date filter ignored.", "warning")
    search = request.args.get("q", "").strip()
    if search:
        term = f"%{search[:40]}%"
        query = query.filter(or_(
            ParkingSession.ticket_number.like(term),
            ParkingSession.vehicle.has(Vehicle.plate_number.like(term)),
        ))
    sort = request.args.get("sort", "entry_desc")
    order = {
        "entry_asc": ParkingSession.entry_time.asc(),
        "entry_desc": ParkingSession.entry_time.desc(),
        "fee_desc": ParkingSession.amount_due.desc(),
    }.get(sort, ParkingSession.entry_time.desc())
    page = query.order_by(order).paginate(
        page=request.args.get("page", 1, type=int), per_page=25, error_out=False
    )
    return render_template(
        "parking/history.html", page=page, search=search, status=status, sort=sort,
        vehicle_types=VehicleType.query.filter_by(is_enabled=True).order_by(VehicleType.name).all(),
        areas=ParkingArea.query.filter_by(status="ACTIVE").order_by(ParkingArea.name).all(),
    )


@parking_bp.get("/receipt/<int:payment_id>")
@login_required
def receipt(payment_id):
    payment = db.get_or_404(Payment, payment_id)
    if current_user.has_role("customer") and payment.parking_session.vehicle.customer_id != current_user.id:
        abort(403)
    if not current_user.has_role("admin", "attendant", "customer"):
        abort(403)
    return render_template("parking/receipt.html", payment=payment)
