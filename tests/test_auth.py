"""Auth: registration, login, and token checks.

These pin down the security promises from Day 2, not just the happy path:
the hash never leaves the API, and a failed login gives no hint about
whether the email exists.
"""

EMAIL = "agent@example.com"
PASSWORD = "correct-horse-battery"


def register(client, email: str = EMAIL, password: str = PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password})


def login(client, email: str = EMAIL, password: str = PASSWORD):
    # OAuth2 password flow: form fields named username/password, not JSON.
    return client.post("/auth/login", data={"username": email, "password": password})


def test_register_creates_an_agent_and_never_returns_the_password(client):
    response = register(client)

    assert response.status_code == 201
    body = response.json()
    # Exact key set: proves nothing extra, like a password hash, leaks out.
    assert set(body) == {"id", "email", "role", "is_active", "created_at"}
    assert body["email"] == EMAIL
    assert body["role"] == "agent"
    assert body["is_active"] is True


def test_register_rejects_a_duplicate_email(client):
    register(client)

    response = register(client)

    assert response.status_code == 409


def test_register_rejects_a_short_password(client):
    response = register(client, password="short")

    assert response.status_code == 422


def test_login_returns_a_token_that_authenticates(client):
    register(client)

    response = login(client)

    assert response.status_code == 200
    token = response.json()
    assert token["token_type"] == "bearer"

    me = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL


def test_wrong_password_and_unknown_email_are_indistinguishable(client):
    register(client)

    wrong_password = login(client, password="not-the-password")
    unknown_email = login(client, email="nobody@example.com")

    # Same status AND same body: the response must not reveal which
    # emails have accounts (user enumeration).
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_me_rejects_a_missing_or_forged_token(client):
    missing = client.get("/auth/me")
    forged = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"})

    assert missing.status_code == 401
    assert forged.status_code == 401