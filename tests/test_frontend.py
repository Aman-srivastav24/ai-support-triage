"""The frontend is served, does not shadow the API, and never uses innerHTML."""

from app.main import STATIC_DIR


def test_frontend_is_served_at_the_root(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "AI Support Triage" in response.text


def test_the_frontend_mount_does_not_shadow_the_api(client):
    # The "/" mount matches every path; if it were registered before the
    # routers, these would return the frontend (or 404) instead of the API.
    assert client.get("/openapi.json").json()["info"]["title"] == "AI Support Triage API"
    assert client.get("/health").status_code == 200


def test_the_frontend_never_uses_innerhtml():
    # The agent view displays text typed by strangers and written by an LLM.
    # textContent treats it as text; innerHTML would parse it as HTML (XSS).
    # This turns a code-review rule into a check that runs on every push.
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert "innerHTML" not in html