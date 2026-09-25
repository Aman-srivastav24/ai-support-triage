"""Seed a deployed instance: demo agent, admin, and the sample documents.

Safe to run more than once: an existing user or document comes back as 409
and is treated as already done.

Usage, from the project root:
    BASE_URL=https://<service>.onrender.com DATABASE_URL="$NEON_URL" \
        python scripts/seed_production.py

DATABASE_URL must point at the SAME database the deployed app uses. It is
used for one thing only: promoting the admin, because there is no admin
creation endpoint. The script checks afterwards that the deployed app
actually sees the promotion.

Deliberately imports nothing from `app`: this talks to a deployed API over
HTTP, and must never pick up local settings from .env by accident.
"""

import getpass
import os
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

# Titles match the dev database, so evals can refer to documents by title
# in both environments.
DOCUMENTS = {
    "billing.txt": "Billing and Payments",
    "accounts.txt": "Accounts and Delivery",
    "troubleshooting.txt": "Troubleshooting",
}

# example.com is reserved for documentation (RFC 2606): no real inbox exists.
DEMO_AGENT_EMAIL = "demo-agent@example.com"


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} is not set")
    return value


def register(client: httpx.Client, email: str, password: str) -> None:
    response = client.post("/auth/register", json={"email": email, "password": password})
    if response.status_code == 201:
        print(f"registered {email}")
    elif response.status_code == 409:
        print(f"{email} already exists")
    else:
        sys.exit(f"register {email} failed: {response.status_code} {response.text}")


def login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", data={"username": email, "password": password})
    if response.status_code != 200:
        sys.exit(f"login {email} failed: {response.status_code} {response.text}")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def promote_to_admin(database_url: str, email: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text("UPDATE users SET role = 'admin' WHERE email = :email"),
                {"email": email},
            )
    finally:
        engine.dispose()
    if result.rowcount != 1:
        sys.exit(f"promotion matched {result.rowcount} users for {email}")
    print(f"promoted {email} to admin")


def upload(client: httpx.Client, headers: dict, path: Path, title: str) -> str | None:
    response = client.post(
        "/documents",
        headers=headers,
        files={"file": (path.name, path.read_bytes(), "text/plain")},
        data={"title": title},
    )
    if response.status_code == 202:
        print(f"{title}: accepted")
        return response.json()["id"]
    if response.status_code == 409:
        print(f"{title}: already uploaded")
        return None
    sys.exit(f"upload {title} failed: {response.status_code} {response.text}")


def wait_until_ready(
    client: httpx.Client, headers: dict, doc_id: str, title: str, timeout: float = 60
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        doc = client.get(f"/documents/{doc_id}", headers=headers).json()
        if doc["status"] == "ready":
            print(f"{title}: ready, {doc['chunk_count']} chunk(s)")
            return
        if doc["status"] == "failed":
            sys.exit(f"{title}: ingestion failed: {doc['error_message']}")
        time.sleep(1)
    sys.exit(f"{title}: not ready after {timeout:.0f}s")


def main() -> None:
    base_url = require_env("BASE_URL").rstrip("/")
    database_url = require_env("DATABASE_URL")

    admin_email = input("Admin email: ").strip()
    admin_password = getpass.getpass("Admin password: ")
    demo_password = getpass.getpass(f"Password for {DEMO_AGENT_EMAIL} (will be PUBLISHED): ")

    # Generous timeout: a free Render service can take about a minute to wake.
    with httpx.Client(base_url=base_url, timeout=90) as client:
        register(client, DEMO_AGENT_EMAIL, demo_password)
        register(client, admin_email, admin_password)
        promote_to_admin(database_url, admin_email)

        headers = login(client, admin_email, admin_password)
        me = client.get("/auth/me", headers=headers).json()
        if me["role"] != "admin":
            sys.exit(
                "the deployed app does not see the promotion: DATABASE_URL points "
                "at a different database than BASE_URL"
            )
        print(f"{admin_email} confirmed as admin by the deployed app")

        for filename, title in DOCUMENTS.items():
            doc_id = upload(client, headers, Path("sample_docs") / filename, title)
            if doc_id is not None:
                wait_until_ready(client, headers, doc_id, title)


if __name__ == "__main__":
    main()