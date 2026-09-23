import hashlib
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urljoin, urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db, limiter
from app.models import PasswordResetToken, Role, User, utcnow
from app.security.validators import USERNAME_RE, normalize_email, validate_password
from app.services.audit_service import record_audit


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_next(target):
    if not target:
        return False
    reference = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target or ""))
    return test.scheme in ("http", "https") and reference.netloc == test.netloc


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        identity = request.form.get("identity", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter((User.username == identity) | (User.email == identity)).first()
        now = utcnow()
        valid = bool(user and user.is_active and (not user.locked_until or user.locked_until <= now))
        valid = valid and user.check_password(password)
        if valid:
            session.clear()
            login_user(user, remember=False, fresh=True)
            session.permanent = True
            session["session_version"] = user.session_version
            user.failed_login_count = 0
            user.locked_until = None
            user.last_login_at = now
            record_audit("LOGIN", "user", user.id, user=user)
            db.session.commit()
            next_url = request.args.get("next")
            return redirect(next_url if _safe_next(next_url) else url_for("dashboard.index"))

        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= 5:
                user.locked_until = now + timedelta(minutes=15)
        record_audit("LOGIN_FAILED", "authentication", metadata={"identity": identity[:80]}, user=user)
        current_app.logger.warning("Login failed ip=%s", request.remote_addr)
        db.session.commit()
        flash("Invalid username or password.", "error")
    return render_template("auth/login.html")


@auth_bp.post("/logout")
@login_required
def logout():
    user = current_user._get_current_object()
    record_audit("LOGOUT", "user", user.id, user=user)
    db.session.commit()
    logout_user()
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("3 per hour", methods=["POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        email = normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        error = validate_password(password, current_app.config["PASSWORD_MIN_LENGTH"])
        if not USERNAME_RE.fullmatch(username):
            error = "Username must be 3–50 characters using letters, numbers, dots, dashes, or underscores."
        elif not email:
            error = "Enter a valid email address."
        elif User.query.filter((User.username == username) | (User.email == email)).first():
            error = "Unable to create an account with those details."
        if error:
            flash(error, "error")
        else:
            role = Role.query.filter_by(name="customer").first()
            if not role:
                role = Role(name="customer", description="Customer")
                db.session.add(role)
            user = User(
                username=username, email=email, full_name=request.form.get("full_name", "").strip()[:120],
                role=role,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            record_audit("USER_REGISTERED", "user", user.id, user=user)
            db.session.commit()
            flash("Account created. You can now sign in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


def _send_reset_email(user, raw_token):
    host = current_app.config.get("SMTP_HOST")
    if not host:
        current_app.logger.warning("Password reset requested but SMTP is not configured.")
        return
    link = url_for("auth.reset_password", token=raw_token, _external=True, _scheme="https")
    message = EmailMessage()
    message["Subject"] = "Parking account password reset"
    message["From"] = current_app.config["SMTP_FROM"]
    message["To"] = user.email
    message.set_content(f"Use this link within {current_app.config['RESET_TOKEN_MINUTES']} minutes: {link}")
    with smtplib.SMTP(host, current_app.config["SMTP_PORT"], timeout=10) as client:
        if current_app.config["SMTP_USE_TLS"]:
            client.starttls()
        if current_app.config.get("SMTP_USERNAME"):
            client.login(current_app.config["SMTP_USERNAME"], current_app.config["SMTP_PASSWORD"])
        client.send_message(message)


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("3 per hour", methods=["POST"])
def forgot_password():
    if request.method == "POST":
        identity = request.form.get("identity", "").strip().lower()
        user = User.query.filter((User.username == identity) | (User.email == identity)).first()
        if user and user.is_active:
            raw_token = secrets.token_urlsafe(32)
            reset = PasswordResetToken(
                user=user, token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                expires_at=utcnow() + timedelta(minutes=current_app.config["RESET_TOKEN_MINUTES"]),
            )
            db.session.add(reset)
            record_audit("PASSWORD_RESET_REQUESTED", "user", user.id, user=user)
            db.session.commit()
            try:
                _send_reset_email(user, raw_token)
            except Exception:
                current_app.logger.exception("Password reset email delivery failed for user_id=%s", user.id)
        flash("If the account exists, password reset instructions will be sent.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def reset_password(token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    reset = PasswordResetToken.query.filter_by(token_hash=token_hash, used_at=None).first()
    if not reset or reset.expires_at < utcnow() or not reset.user.is_active:
        flash("That reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        error = validate_password(password, current_app.config["PASSWORD_MIN_LENGTH"])
        if error:
            flash(error, "error")
        else:
            reset.user.set_password(password)
            reset.user.session_version += 1
            reset.user.failed_login_count = 0
            reset.user.locked_until = None
            reset.used_at = utcnow()
            record_audit("PASSWORD_RESET", "user", reset.user.id, user=reset.user)
            db.session.commit()
            flash("Your password was reset. Please sign in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html")


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
@limiter.limit("5 per hour", methods=["POST"])
def change_password():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        password = request.form.get("password", "")
        error = validate_password(password, current_app.config["PASSWORD_MIN_LENGTH"])
        if not current_user.check_password(current):
            error = "The current password is incorrect."
        if error:
            flash(error, "error")
        else:
            user = current_user._get_current_object()
            user.set_password(password)
            user.session_version += 1
            record_audit("PASSWORD_CHANGED", "user", user.id, user=user)
            db.session.commit()
            logout_user()
            session.clear()
            flash("Password changed. Please sign in again.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/change_password.html")
