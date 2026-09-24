"""Shared test setup. pytest loads this before any test module.

Order matters. app.db.session and app.main read settings at import time,
and get_settings() caches the first values it sees. So every environment
variable below must be set BEFORE anything from `app` is imported, and the
guard must confirm what the app actually resolved, not what we intended.
"""

import os
from urllib.parse import urlparse

from sqlalchemy.engine import make_url

# --- 1. Point everything at test infrastructure ---------------------------
# Assigned, never setdefault: a value already exported in the shell must not
# silently win and aim the tests at the dev database.
# TEST_* variables let CI (Day 14) supply its own addresses; the defaults are
# the local Compose stack. The password is the dev container's, already in
# docker-compose.yml — tracked for Day 12, not a new secret.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://triage:triage@localhost:5433/triage_test",
)
os.environ["REDIS_URL"] = os.environ.get(
    "TEST_REDIS_URL",
    "redis://localhost:6379/15",
)
os.environ["JWT_SECRET_KEY"] = "test-secret-not-for-production-at-least-32-bytes"

# Tripwires: if any code path reaches a real provider, it fails with a 401
# instead of spending quota.
os.environ["GROQ_API_KEY"] = "test-not-a-real-key"
os.environ["GEMINI_API_KEY"] = "test-not-a-real-key"

# --- 2. Only now is it safe to import from the app ------------------------
from app.core.config import get_settings  # noqa: E402

_settings = get_settings()

# --- 3. Safety guard: check what the app RESOLVED -------------------------
# Tests truncate tables and flush Redis. Pointed at dev, that destroys data
# with no warning, so refuse to start unless both targets are clearly test.
_db_name = make_url(_settings.database_url).database or ""
if not _db_name.endswith("_test"):
    raise RuntimeError(
        f"Refusing to run tests: database '{_db_name}' does not end in '_test'."
    )

_redis_db = urlparse(_settings.redis_url).path.lstrip("/") or "0"
if _redis_db == "0":
    raise RuntimeError(
        "Refusing to run tests: Redis database 0 is the dev cache. "
        "Use a numbered test database, e.g. redis://localhost:6379/15."
    )

# --- 4. Fakes ----------------------------------------------------------------
# Replace the real providers through app.dependency_overrides. Both record
# every call, so a test can prove the fake was actually used rather than
# passing because a real call failed and fell back (classify_ticket returns
# OTHER on failure, which escalates, which looks like a pass).

import hashlib  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402

import pytest  # noqa: E402

from app.models.chunk import Chunk  # noqa: E402
from app.schemas.classification import TicketCategory  # noqa: E402

# Read from the model, not retyped: a copied constant drifts out of sync.
EMBEDDING_DIM = Chunk.__table__.c.embedding.type.dim


class FakeEmbedder:
    """Deterministic bag-of-words embedder (feature hashing).

    Texts sharing words get high cosine similarity; unrelated texts get ~0.
    Enough structure for retrieval and the similarity floor to behave
    meaningfully, with no network and identical output on every run.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def embed(
        self, text: str, *, task_type: str, use_cache: bool = False
    ) -> list[float]:
        self.calls.append((text, task_type))

        vector = [0.0] * EMBEDDING_DIM
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            bucket = int(hashlib.sha256(word.encode()).hexdigest(), 16) % EMBEDDING_DIM
            vector[bucket] += 1.0

        magnitude = math.sqrt(sum(v * v for v in vector))
        if magnitude == 0:
            # No words at all. Return a fixed unit vector rather than a zero
            # vector, which has no direction and breaks cosine distance.
            vector[0] = 1.0
            return vector
        return [v / magnitude for v in vector]


class FakeLLM:
    """Scripted LLM. Tests set what it returns and inspect what it was asked."""

    def __init__(self) -> None:
        self.category = TicketCategory.BILLING
        self.reply = "Refunds are available within 14 days of the first charge."
        self.classify_calls: list[tuple[str, str]] = []
        self.draft_calls: list[tuple[str, list[str]]] = []

    def classify(self, subject: str, body: str) -> TicketCategory:
        self.classify_calls.append((subject, body))
        return self.category

    def draft(self, question: str, context_chunks: list[str]) -> str:
        self.draft_calls.append((question, context_chunks))
        return self.reply


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    """A fresh fake embedder for each test."""
    return FakeEmbedder()


@pytest.fixture
def fake_llm() -> FakeLLM:
    """A fresh fake LLM for each test. Defaults: billing, a grounded answer."""
    return FakeLLM()

# --- 5. Clean state and the test client -------------------------------------

import redis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.providers import get_embedder, get_llm  # noqa: E402


@pytest.fixture
def clean_state():
    """Empty every app table and the test Redis database BEFORE the test.

    Truncation, not transaction rollback: services commit on their own, and
    the ingestion background task opens its own session, so a rollback
    could not undo everything a test writes.

    Cleans before rather than after, so a crashed test cannot leave the
    next one dirty, and the last failure's data stays inspectable.
    """
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).scalars().all()
        if tables:
            conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))

    # FLUSHDB clears only the connected database (15, checked by the guard).
    # FLUSHALL would clear every database on the server, including dev's 0.
    redis.from_url(_settings.redis_url).flushdb()


@pytest.fixture
def client(clean_state, fake_llm, fake_embedder):
    """The real app, on a clean database, with fake AI providers installed."""
    app.dependency_overrides[get_llm] = lambda: fake_llm
    app.dependency_overrides[get_embedder] = lambda: fake_embedder
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()

# --- 6. Authenticated users --------------------------------------------------

TEST_PASSWORD = "correct-horse-battery"


def _register(client, email: str) -> None:
    response = client.post(
        "/auth/register", json={"email": email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 201, response.text


def _bearer(client, email: str) -> dict[str, str]:
    response = client.post(
        "/auth/login", data={"username": email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def agent_headers(client) -> dict[str, str]:
    """Authorization header for a freshly registered agent."""
    _register(client, "agent@example.com")
    return _bearer(client, "agent@example.com")


@pytest.fixture
def admin_headers(client) -> dict[str, str]:
    """Authorization header for an admin.

    There is no admin-creation endpoint (a Day 2 open item), so this does
    what a human does today: register, then promote with SQL. Promoted
    before login so the token's role claim matches, though authorisation
    reads the database either way.
    """
    _register(client, "admin@example.com")
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE users SET role = 'admin' WHERE email = :email"),
            {"email": "admin@example.com"},
        )
        assert result.rowcount == 1, "admin promotion matched no user"
    return _bearer(client, "admin@example.com")