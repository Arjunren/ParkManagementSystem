import csv
import io
from datetime import datetime, timedelta

from flask import Blueprint, Response, render_template, request
from flask_login import login_required
from sqlalchemy import extract, func

from app.extensions import db
from app.models import ParkingArea, ParkingSession, ParkingSlot, Payment, PaymentMethod, Vehicle, VehicleType, utcnow
from app.security.decorators import role_required


reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


def _date_range():
    today = utcnow().date()
    period = request.args.get("period", "")
    if not request.args.get("start") and period in {"day", "week", "month"}:
        if period == "day":
            start_date = today
        elif period == "week":
            start_date = today - timedelta(days=today.weekday())
        else:
            start_date = today.replace(day=1)
        return datetime.combine(start_date, datetime.min.time()), datetime.combine(today + timedelta(days=1), datetime.min.time())
    try:
        start = datetime.strptime(request.args.get("start", ""), "%Y-%m-%d")
    except ValueError:
        start = datetime.combine(today - timedelta(days=29), datetime.min.time())
    try:
        end = datetime.strptime(request.args.get("end", ""), "%Y-%m-%d") + timedelta(days=1)
    except ValueError:
        end = datetime.combine(today + timedelta(days=1), datetime.min.time())
    if end <= start or (end - start).days > 366:
        end = start + timedelta(days=31)
    return start, end


def _filtered_sessions(start, end):
    query = ParkingSession.query.filter(ParkingSession.entry_time >= start, ParkingSession.entry_time < end)
    vehicle_type_id = request.args.get("vehicle_type_id", type=int)
    if vehicle_type_id:
        query = query.join(Vehicle).filter(Vehicle.vehicle_type_id == vehicle_type_id)
    return query


@reports_bp.get("/")
@login_required
@role_required("admin")
def index():
    start, end = _date_range()
    sessions = _filtered_sessions(start, end)
    entries = sessions.count()
    exit_query = ParkingSession.query.filter(
        ParkingSession.exit_time >= start, ParkingSession.exit_time < end,
    )
    vehicle_type_id = request.args.get("vehicle_type_id", type=int)
    if vehicle_type_id:
        exit_query = exit_query.join(Vehicle).filter(Vehicle.vehicle_type_id == vehicle_type_id)
    exits = exit_query.count()
    active = ParkingSession.query.filter_by(status="ACTIVE").count()
    payment_query = Payment.query.filter(Payment.paid_at >= start, Payment.paid_at < end, Payment.status == "COMPLETED")
    vehicle_type_id = request.args.get("vehicle_type_id", type=int)
    if vehicle_type_id:
        payment_query = payment_query.join(ParkingSession).join(Vehicle).filter(Vehicle.vehicle_type_id == vehicle_type_id)
    method_id = request.args.get("payment_method_id", type=int)
    if method_id:
        payment_query = payment_query.filter(Payment.payment_method_id == method_id)
    revenue = payment_query.with_entities(func.coalesce(func.sum(Payment.amount_due), 0)).scalar()
    average_duration = sessions.filter(ParkingSession.duration_minutes.is_not(None)).with_entities(
        func.avg(ParkingSession.duration_minutes)
    ).scalar() or 0
    total_slots = ParkingSlot.query.count()
    occupied = ParkingSlot.query.filter_by(status="OCCUPIED").count()
    occupancy = round((occupied / total_slots * 100), 1) if total_slots else 0
    peak_hours = sessions.with_entities(
        extract("hour", ParkingSession.entry_time).label("hour"), func.count(ParkingSession.id).label("count")
    ).group_by("hour").order_by(func.count(ParkingSession.id).desc()).limit(5).all()
    area_usage = (
        sessions.join(ParkingSlot).join(ParkingArea)
        .with_entities(ParkingArea.name, func.count(ParkingSession.id).label("count"))
        .group_by(ParkingArea.id, ParkingArea.name).order_by(func.count(ParkingSession.id).desc()).limit(5).all()
    )
    slot_usage = (
        sessions.join(ParkingSlot)
        .with_entities(ParkingSlot.code, func.count(ParkingSession.id).label("count"))
        .group_by(ParkingSlot.id, ParkingSlot.code).order_by(func.count(ParkingSession.id).desc()).limit(5).all()
    )
    return render_template(
        "reports/index.html", start=start, end=end - timedelta(days=1), entries=entries, exits=exits,
        active=active, revenue=revenue, average_duration=average_duration, occupancy=occupancy,
        peak_hours=peak_hours, area_usage=area_usage, slot_usage=slot_usage,
        vehicle_types=VehicleType.query.filter_by(is_enabled=True).all(),
        payment_methods=PaymentMethod.query.filter_by(is_enabled=True).all(),
    )


def _csv_safe(value):
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


@reports_bp.get("/parking.csv")
@login_required
@role_required("admin")
def parking_csv():
    start, end = _date_range()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Ticket", "Plate", "Vehicle type", "Slot", "Entry", "Exit", "Minutes", "Fee", "Status"])
    for item in _filtered_sessions(start, end).order_by(ParkingSession.entry_time).all():
        writer.writerow([_csv_safe(value) for value in (
            item.ticket_number, item.vehicle.plate_number, item.vehicle.vehicle_type.name, item.slot.code,
            item.entry_time.isoformat(sep=" "), item.exit_time.isoformat(sep=" ") if item.exit_time else "",
            item.duration_minutes, item.amount_due, item.status,
        )])
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=parking-{start:%Y%m%d}-{end - timedelta(days=1):%Y%m%d}.csv"},
    )
