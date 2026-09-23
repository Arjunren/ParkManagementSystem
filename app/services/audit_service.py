from flask import has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


SENSITIVE_KEYS = {"password", "token", "secret", "authorization", "card_number", "cvv", "session"}


def _safe_metadata(metadata):
    return {
        str(key)[:80]: (
            "[REDACTED]" if any(secret in str(key).lower() for secret in SENSITIVE_KEYS) else str(value)[:500]
        )
        for key, value in (metadata or {}).items()
    }


def record_audit(action, resource, resource_id=None, metadata=None, user=None):
    actor = user
    if actor is None and has_request_context() and current_user.is_authenticated:
        actor = current_user
    log = AuditLog(
        user_id=getattr(actor, "id", None),
        username=getattr(actor, "username", None),
        action=action[:80],
        resource=resource[:80],
        resource_id=str(resource_id)[:80] if resource_id is not None else None,
        ip_address=(request.remote_addr[:45] if has_request_context() and request.remote_addr else None),
        metadata_json=_safe_metadata(metadata),
    )
    db.session.add(log)
    return log
