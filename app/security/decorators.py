from functools import wraps

from flask import abort, current_app, request
from flask_login import current_user

from app.extensions import db
from app.services.audit_service import record_audit


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not current_user.has_role(*roles):
                record_audit(
                    "AUTHORIZATION_DENIED", "endpoint", request.endpoint,
                    {"required_roles": list(roles)}, user=current_user,
                )
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                current_app.logger.warning("Authorization denied for user_id=%s endpoint=%s", current_user.id, request.endpoint)
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator
