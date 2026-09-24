"""Smoke test: the test client reaches the app, and the app reaches the
test database and test Redis. If this fails, every other test is suspect."""


def test_health_reports_database_and_redis_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok"},
    }