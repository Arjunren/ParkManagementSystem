import re
from decimal import Decimal, InvalidOperation

from email_validator import EmailNotValidError, validate_email


PLATE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 -]{1,18}[A-Z0-9]$")
SLOT_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,28}[A-Z0-9]$")
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,50}$")
PHONE_RE = re.compile(r"^[0-9+() .-]{7,30}$")


def normalize_plate(value):
    return " ".join((value or "").strip().upper().split())


def validate_plate(value):
    value = normalize_plate(value)
    return value if PLATE_RE.fullmatch(value) else None


def validate_slot_code(value):
    value = (value or "").strip().upper()
    return value if SLOT_RE.fullmatch(value) else None


def normalize_email(value):
    try:
        return validate_email(value, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def validate_password(password, minimum=10):
    if len(password or "") < minimum:
        return f"Password must contain at least {minimum} characters."
    checks = [r"[A-Z]", r"[a-z]", r"[0-9]", r"[^A-Za-z0-9]"]
    if not all(re.search(pattern, password) for pattern in checks):
        return "Password must include uppercase, lowercase, number, and special characters."
    return None


def parse_money(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
        return amount if amount >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None
