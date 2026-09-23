from tests.conftest import login
from app.models import AuditLog


def test_attendant_cannot_access_admin_routes(app, client):
    login(client, "attendant")
    assert client.get("/admin/users").status_code == 403
    assert client.get("/reports/").status_code == 403
    with app.app_context():
        assert AuditLog.query.filter_by(action="AUTHORIZATION_DENIED").count() == 2


def test_customer_cannot_access_attendant_routes(client):
    login(client, "customer")
    assert client.get("/parking/entry").status_code == 403
    assert client.get("/parking/active").status_code == 403
    response = client.get("/")
    assert response.status_code == 302
    assert "/parking/history" in response.headers["Location"]


def test_unauthenticated_user_redirected(client):
    response = client.get("/parking/history")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
