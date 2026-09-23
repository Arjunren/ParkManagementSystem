import logging
import os
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
from flask import Flask, render_template, session
from flask_login import current_user, logout_user

load_dotenv()

from config import CONFIGS
from .extensions import csrf, db, limiter, login_manager, migrate


def create_app(config_name=None):
    name = config_name or os.getenv("FLASK_ENV", "development")
    config = CONFIGS.get(name, CONFIGS["development"])
    if name == "production":
        config.validate()

    app = Flask(__name__)
    app.config.from_object(config)
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"
    login_manager.session_protection = "strong"

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from .routes.admin import admin_bp
    from .routes.auth import auth_bp
    from .routes.dashboard import dashboard_bp
    from .routes.parking import parking_bp
    from .routes.reports import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(parking_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(reports_bp)

    from .security.headers import apply_security_headers

    app.after_request(apply_security_headers)

    @app.before_request
    def enforce_session_version():
        if current_user.is_authenticated:
            if session.get("session_version") != current_user.session_version:
                logout_user()
                session.clear()

    @app.context_processor
    def inject_globals():
        return {"facility_name": app.config["FACILITY_NAME"]}

    register_error_handlers(app)
    register_commands(app)
    configure_logging(app)
    return app


def configure_logging(app):
    if app.testing:
        return
    os.makedirs("logs", exist_ok=True)
    handler = RotatingFileHandler("logs/parking.log", maxBytes=1_000_000, backupCount=5)
    handler.setFormatter(logging.Formatter(
        '{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}'
    ))
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)


def register_error_handlers(app):
    for code in (400, 401, 403, 404, 405, 429, 500):
        app.register_error_handler(
            code, lambda error, status=code: (render_template("errors/error.html", code=status), status)
        )


def register_commands(app):
    import click
    from .models import Role, User
    from .security.validators import validate_password

    @app.cli.command("create-admin")
    def create_admin():
        """Interactively create the first administrator."""
        username = click.prompt("Username").strip().lower()
        email = click.prompt("Email").strip().lower()
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        error = validate_password(password)
        if error:
            raise click.ClickException(error)
        if User.query.filter((User.username == username) | (User.email == email)).first():
            raise click.ClickException("That username or email is already registered.")
        role = Role.query.filter_by(name="admin").first()
        if not role:
            role = Role(name="admin", description="System administrator")
            db.session.add(role)
        user = User(username=username, email=email, role=role, is_enabled=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo("Administrator created.")

    @app.cli.command("seed-reference-data")
    def seed_reference_data():
        """Create roles, payment methods, and common vehicle types."""
        from .models import PaymentMethod, VehicleType
        for role_name in ("admin", "attendant", "customer"):
            if not Role.query.filter_by(name=role_name).first():
                db.session.add(Role(name=role_name, description=role_name.title()))
        for name in ("Motorcycle", "Sedan", "SUV", "Van", "Pickup", "Truck", "Bus", "Electric Vehicle"):
            if not VehicleType.query.filter_by(name=name).first():
                db.session.add(VehicleType(name=name))
        for name in ("Cash", "GCash", "Maya", "Credit Card", "Debit Card", "Other"):
            if not PaymentMethod.query.filter_by(name=name).first():
                db.session.add(PaymentMethod(name=name))
        db.session.commit()
        click.echo("Reference data created.")
