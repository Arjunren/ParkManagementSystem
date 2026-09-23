import hashlib
from datetime import timedelta

from app.extensions import db
from app.models import PasswordResetToken, User, utcnow
from tests.conftest import login


def test_login_and_logout(client):
    response = login(client)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert client.get("/").status_code == 200
    response = client.post("/auth/logout")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_invalid_login_is_generic_and_injection_safe(client):
    response = client.post(
        "/auth/login", data={"identity": "admin' OR 1=1 --", "password": "wrong"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Invalid username or password" in response.data
    assert b"SQL" not in response.data


def test_lockout_after_repeated_failures(app, client):
    for _ in range(5):
        client.post("/auth/login", data={"identity": "admin", "password": "wrong"})
    with app.app_context():
        user = User.query.filter_by(username="admin").one()
        assert user.locked_until > utcnow()


def test_password_change_invalidates_session(app, logged_admin):
    response = logged_admin.post("/auth/change-password", data={
        "current_password": "ValidPass1!", "password": "NewValidPass2!",
    })
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
    assert login(logged_admin, password="NewValidPass2!").status_code == 302


def test_server_side_session_version_check(app, logged_admin):
    with app.app_context():
        user = User.query.filter_by(username="admin").one()
        user.session_version += 1
        db.session.commit()
    response = logged_admin.get("/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_registration_escapes_xss(client, logged_admin):
    client.post("/auth/logout")
    response = client.post("/auth/register", data={
        "username": "safeuser", "email": "safe@example.com",
        "full_name": "<script>alert(1)</script>", "password": "ValidPass1!",
    })
    assert response.status_code == 302
    login(client)
    page = client.get("/admin/users")
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in page.data
    assert b"<script>alert(1)</script>" not in page.data


def test_csrf_rejects_missing_token(app, client):
    app.config["WTF_CSRF_ENABLED"] = True
    response = client.post("/auth/login", data={"identity": "admin", "password": "ValidPass1!"})
    assert response.status_code == 400


def test_password_reset_token_is_single_use(app, client):
    raw_token = "test-reset-token-with-enough-entropy-for-fixture"
    with app.app_context():
        user = User.query.filter_by(username="admin").one()
        db.session.add(PasswordResetToken(
            user=user,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=utcnow() + timedelta(minutes=30),
        ))
        db.session.commit()
    response = client.post(f"/auth/reset-password/{raw_token}", data={"password": "ResetValid3!"})
    assert response.status_code == 302
    assert login(client, password="ResetValid3!").status_code == 302
    client.post("/auth/logout")
    response = client.get(f"/auth/reset-password/{raw_token}", follow_redirects=True)
    assert b"invalid or has expired" in response.data
