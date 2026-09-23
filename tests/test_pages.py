from tests.conftest import login


def test_all_admin_get_pages_render(logged_admin):
    urls = [
        "/", "/parking/entry", "/parking/active", "/parking/history",
        "/admin/areas", "/admin/slots", "/admin/vehicle-types", "/admin/rates",
        "/admin/payment-methods", "/admin/users", "/admin/payments",
        "/admin/audit-logs", "/admin/settings", "/reports/",
        "/reports/?period=day", "/reports/?period=week", "/reports/?period=month",
    ]
    for url in urls:
        response = logged_admin.get(url)
        assert response.status_code == 200, url


def test_security_headers_are_present(client):
    response = client.get("/auth/login")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
