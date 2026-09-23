from datetime import datetime, timedelta
from decimal import Decimal

from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.models import ParkingSession, ParkingSlot, Payment, utcnow


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/")
@login_required
def index():
    if current_user.has_role("customer"):
        return redirect(url_for("parking.history"))
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    slot_counts = dict(
        ParkingSlot.query.with_entities(ParkingSlot.status, func.count(ParkingSlot.id))
        .group_by(ParkingSlot.status).all()
    )
    def revenue_since(since):
        return Payment.query.with_entities(func.coalesce(func.sum(Payment.amount_due), 0)).filter(
            Payment.status == "COMPLETED", Payment.paid_at >= since
        ).scalar() or Decimal("0")
    stats = {
        "total_slots": sum(slot_counts.values()),
        "available": slot_counts.get("AVAILABLE", 0),
        "occupied": slot_counts.get("OCCUPIED", 0),
        "reserved": slot_counts.get("RESERVED", 0),
        "unavailable": slot_counts.get("MAINTENANCE", 0) + slot_counts.get("DISABLED", 0),
        "active": ParkingSession.query.filter_by(status="ACTIVE").count(),
        "entered_today": ParkingSession.query.filter(ParkingSession.entry_time >= today).count(),
        "exited_today": ParkingSession.query.filter(ParkingSession.exit_time >= today).count(),
        "revenue_today": revenue_since(today),
        "revenue_week": revenue_since(week),
        "revenue_month": revenue_since(month),
    }
    recent = ParkingSession.query.order_by(ParkingSession.entry_time.desc()).limit(8).all()
    return render_template("dashboard.html", stats=stats, recent=recent)
