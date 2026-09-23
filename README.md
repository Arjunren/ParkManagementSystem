# ParkFlow Parking Management System

ParkFlow is a database-driven parking operations system built with Flask, SQLAlchemy, MySQL, server-rendered HTML, compiled Tailwind CSS, and small amounts of vanilla JavaScript. It supports administrators, parking attendants, and restricted customer accounts.

## Features

- Secure login, logout, customer registration, password change, expiring password-reset tokens, account throttling, and session invalidation
- Server-enforced role-based access control for administrator, attendant, and customer routes
- Parking areas, slots, vehicle types, versioned parking rates, and configurable payment methods
- Row-locked, atomic vehicle entry and exit workflows
- Server-side fee calculation with grace period, base duration, hourly rate, flat rate, daily maximum, overnight, and lost-ticket fees
- Printable receipts, searchable history, payments, dashboard metrics, utilization/revenue reports, and formula-safe CSV export
- CSRF protection, strict input validation, automatic template escaping, CSP and other security headers, rate limiting, generic error pages, and structured audit logging
- MySQL/XAMPP support through PyMySQL and schema migrations through Flask-Migrate/Alembic
- Pytest unit and integration tests

## Requirements

- Python 3.10 or newer
- MySQL 8+ or MariaDB 10.6+ (XAMPP is suitable for local development)
- Node.js 18+ only when rebuilding Tailwind CSS

## XAMPP / MySQL setup

Start MySQL from the XAMPP control panel. In phpMyAdmin, run the following once with an appropriately privileged account. Use a different strong password in real installations.

```sql
CREATE DATABASE parking_management CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'parking_user'@'localhost' IDENTIFIED BY 'replace-with-a-strong-password';
GRANT ALL PRIVILEGES ON parking_management.* TO 'parking_user'@'localhost';
FLUSH PRIVILEGES;
```

Do not run the application as the MySQL root user.

## Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`, set the database password, and create a random secret:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put that result in `SECRET_KEY`. Then initialize the schema and reference data:

```powershell
$env:FLASK_APP = "run.py"
flask db upgrade
flask seed-reference-data
flask create-admin
```

The administrator command prompts for the username, email, and password; no default password exists in the source.

Start the development server:

```powershell
$env:FLASK_ENV = "development"
flask run
```

Open `http://127.0.0.1:5000`. Flask's development server must not be used in production.

## Tailwind CSS

The minified compiled file is committed at `app/static/css/output.css`; Node.js is not required merely to run the application.

```powershell
npm install
npm run css:dev    # watch during UI development
npm run css:build  # minified production build
```

No Tailwind CDN or third-party browser dependency is used. The committed `package-lock.json` pins the frontend dependency tree.

## Database migrations

An initial migration is included. After changing models:

```powershell
flask db migrate -m "Describe the schema change"
flask db upgrade
```

Review generated migrations before applying them. Back up production data before schema changes. Use InnoDB so row locks and atomic transactions behave as intended.

## Tests and dependency auditing

Tests use an isolated in-memory SQLite database and disable rate limits/CSRF except where those controls are specifically tested.

```powershell
python -m pytest -q
python -m pytest --cov=app --cov-report=term-missing
python -m pip_audit -r requirements.txt
npm audit
```

SQLite tests do not reproduce MySQL concurrency semantics. Before a release, also run the workflow tests against a disposable MySQL database and perform a two-attendant concurrency test.

## Production deployment

Set `FLASK_ENV=production`, a random 32+ character `SECRET_KEY`, the production `DATABASE_URL`, SMTP settings, and a shared rate-limit backend. For example:

```dotenv
FLASK_ENV=production
DATABASE_URL=mysql+pymysql://parking_user:strong-password@127.0.0.1/parking_management?charset=utf8mb4
RATELIMIT_STORAGE_URI=redis://127.0.0.1:6379/0
```

Run behind an HTTPS reverse proxy such as IIS, Apache, or nginx. A cross-platform WSGI command is:

```powershell
waitress-serve --listen=127.0.0.1:8080 run:app
```

Terminate TLS at the reverse proxy, forward the original scheme securely, restrict database/network access, rotate logs, and back up the database. If using proxy headers, configure the exact trusted proxy count in the deployment layer; never blindly trust arbitrary forwarded headers.

## Operational notes

- Configure a rate before accepting an entry for a vehicle type. Each parking session stores the selected rate version, preventing later rate edits from changing an in-progress customer's price.
- An occupied slot cannot be manually changed. Vehicle exit and payment update the session and slot in one database transaction.
- Payment screens accept only a method and external reference. Never enter or store PAN/CVV data.
- Password-reset links are delivered only when SMTP is configured. The response remains generic even when an account does not exist.
- Financial records, parking history, and audit logs have no destructive delete routes.
- `memory://` rate limiting is only for development. Use Redis or another shared supported backend when running multiple processes.

See [SECURITY.md](SECURITY.md) for the security architecture, OWASP review, and residual risks.
