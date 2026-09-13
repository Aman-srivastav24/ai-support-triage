# Day 1 Learnings — Backend Spine

**Date:** 13 Sep 2026
**Built:** layered FastAPI skeleton, config, Docker Compose stack, SQLAlchemy models, Alembic migration, `/health`.

This file is a reference. The recall block is still done out loud with it closed.

---

## 1. Vocabulary that was unclear at the start

| Term | Plain meaning in this project |
|---|---|
| **Agent (human)** | A support staff member with a `users` row and `role='agent'`. Logs in, reads AI drafts. |
| **Agent (AI)** | The LangGraph pipeline (Day 4). Code, not a user. No row anywhere. |
| **Ingestion** | Taking an uploaded file and turning it into rows the system can use: extract text → save → chunk → save chunks → (Day 3) embed. |
| **Chunk** | A ~500-token slice of a document, with 50 tokens of overlap to the next one. The unit that gets searched. |
| **Foreign key** | A column that holds another table's primary key. The database refuses to let it point at a row that doesn't exist. |
| **`ON DELETE`** | The rule for what happens to child rows when the parent is deleted: `RESTRICT` (refuse), `CASCADE` (delete children), `SET NULL` (blank the pointer). |
| **Session** | One request's shopping cart for database changes. `commit()` pays, `rollback()` puts everything back, `close()` returns the cart. |
| **Engine** | The shop. Created once per process, owns the connection pool. |
| **Dependency (`Depends`)** | "I need X" declared on a route; FastAPI provides X before the route runs and cleans it up after. |
| **Migration** | A versioned script that changes the database schema, with an `upgrade()` and a `downgrade()`. |

---

## 2. Why the project is layered

```
api/       HTTP in/out. No business logic.
schemas/   Pydantic — the shape of data crossing HTTP.
services/  Business logic. Knows nothing about HTTP.
models/    SQLAlchemy — the shape of data in the database.
db/        Engine, session factory, get_db.
core/      Config, security. Used by every layer.
```

Rule: each layer calls only the layer below. Nothing imports upward.

Why it pays off here specifically:
- **Day 5 tests** call service functions directly with a fake LLM. No HTTP needed.
- **Day 2** `ingest_document()` is called by the upload endpoint *and* the reprocess endpoint. One function, two callers.
- **Day 13** the MCP server calls `search_support_docs()` from a non-HTTP context.

Same code, three callers. That only works if the logic isn't inside a route function.

---

## 3. Schemas vs models — two classes for one thing

`models/ticket.py` → `Ticket(Base)` — SQLAlchemy, describes the **table**. Has every column.
`schemas/ticket.py` → `TicketCreate(BaseModel)` — Pydantic, describes **what a client may send**. Only `customer_email`, `subject`, `body`.

If the SQLAlchemy model were used as the request body, a client could set `status`, `confidence`, `id`. That's **mass assignment** — a real vulnerability class. The two shapes are different because the trust boundaries are different.

---

## 4. `Depends` — what actually happens

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/health")
def health(db: Session = Depends(get_db)): ...
```

On each request FastAPI:
1. Sees `Depends(get_db)`.
2. Calls `get_db()`, runs it to `yield`, takes the yielded session.
3. Passes it in as `db`, runs the route.
4. After the response, resumes `get_db()` past `yield` — `finally` runs, session closes. Even if the route raised.

The `yield` makes it a **generator dependency**: before = setup, after = teardown.

Dependencies compose. Day 2's `get_current_user` will depend on `get_db` and on the `Authorization` header. FastAPI resolves the tree and calls each dependency once per request.

**Interview line:** *Dependency injection means a function declares what it needs and something else provides it. `Depends` is that something else. The route receives a session; it doesn't construct one.*

---

## 5. Why the session is not a global

```python
db = SessionLocal()   # module level — wrong
```

- **Concurrency.** A `Session` is not thread-safe. Two concurrent requests interleave `add()` and `commit()`; request B commits request A's half-finished changes. Works in local testing with one user, corrupts data under load.
- **Lifecycle.** A global session never closes, never returns its connection to the pool, accumulates state across requests.
- **Testing.** `app.dependency_overrides[get_db] = get_test_db` is one line. Overriding a global is monkeypatching module state.

Per-request state travels through function arguments, not globals.

---

## 6. Engine vs session

| | Engine | Session |
|---|---|---|
| How many | One per process | One per request |
| Cost | Expensive (owns TCP connections) | Cheap |
| Lives | Whole app lifetime | Request start → response sent |
| Created by | `create_engine(url)` at import | `SessionLocal()` inside `get_db` |

`pool_pre_ping=True` on the engine: before handing out a pooled connection, send a trivial query. If the connection died while idle (Neon does this), discard it and open a fresh one. Fixes a class of "works for an hour then breaks" bugs on managed Postgres.

---

## 7. Foreign keys and `ON DELETE`, applied

| FK | Rule | Reason |
|---|---|---|
| `chunks.document_id` | `CASCADE` | A chunk is meaningless without its document. |
| `ticket_citations.*` | `CASCADE` | A citation needs both sides. |
| `documents.uploaded_by_id` | `RESTRICT` | Documents outlive the person who uploaded them. |
| `tickets.assigned_agent_id` | `SET NULL` | Tickets outlive the agent; they become unassigned. |

Rule: **`CASCADE` only when the child cannot exist without the parent.**

Two cascades exist: the database `ondelete=` (the truth, enforced for any writer) and SQLAlchemy's `cascade="all, delete-orphan"` on the relationship (keeps the session's in-memory view consistent). Use both.

Why `is_active` instead of deleting users: with `RESTRICT` the delete fails; with `CASCADE` their documents vanish. Neither is what "someone left the company" should do. Deactivate; keep history.

---

## 8. Schema decisions and the interview answer for each

**UUID primary keys.** Ticket IDs are public. Sequential integers leak volume and let anyone enumerate. Cost: 16 bytes vs 8, slightly worse B-tree locality. UUIDv7 exists if that ever matters.

**`VARCHAR` + named `CheckConstraint`, not Postgres `ENUM`.** `ALTER TYPE ... ADD VALUE` historically can't run inside a transaction — which is what Alembic wraps migrations in. Removing an enum value is near-impossible. Statuses change on Days 4 and 10. A varchar with a check constraint is a one-line migration. Type safety lives in Python `StrEnum` + Pydantic.

**Always name constraints** (`ck_users_role`, `uq_chunks_document_index`). Unnamed ones get auto-generated names that vary by database; a later migration that drops one has to guess.

**`TIMESTAMPTZ` everywhere** (`DateTime(timezone=True)`). Plain `TIMESTAMP` is a wall-clock reading with no zone; rows from different servers aren't comparable. UTC internally, convert at the edge.

**`server_default` and `default` both.** `default` fires when SQLAlchemy inserts. `server_default` becomes `DEFAULT ...` in the actual DDL, so raw SQL and migrations also get the right value.

**`raw_text` stored in Postgres.** Day 7 re-chunks with three sizes. Can't re-chunk what you didn't keep. At scale this moves to S3 with a pointer.

**`content_sha256` unique on extracted text**, not file bytes. Same policy as `.pdf` and `.docx` has different bytes, same text. Duplicate chunks crowd out relevant ones in top-k — this is a retrieval-quality guard dressed as a constraint.

**`ticket_citations` on Day 1.** Day 6's eval asks "was the right chunk in the top-k?" Unanswerable unless retrieval results were persisted with scores at processing time.

**Python-side `uuid.uuid4` default.** ID is known before flush; needed to schedule a background task by ID and return it in the same request.

**No `embedding` column yet.** Day 3's migration then teaches adding an extension and an indexed column to a table with rows in it — the real-world migration.

---

## 9. Docker and Compose concepts

**Image vs container.** Image = frozen filesystem snapshot (the recipe). Container = running instance (the meal). `docker pull` downloads the recipe. Images live in `/var/lib/docker/`, shared by every project on the machine — not in your project folder.

**Image names:** `namespace/repository:tag`. No namespace = Docker Official Image. **Never use `latest`** in anything run twice; it changes under you.

**Dockerfile lines that bite people once:**
- `PYTHONUNBUFFERED=1` — without it, logs appear late or never when a container dies.
- `--host 0.0.0.0` — uvicorn's default `127.0.0.1` is unreachable from outside the container.
- JSON-array `CMD ["uvicorn", ...]` — runs as PID 1, so `docker stop` signals reach it. String form wraps it in a shell and it takes 10 s to die.

**`.dockerignore`** — keeps `.venv` (slow, wrong platform), `.env` (secrets baked into a layer forever), `.git` out of the build context.

**Compose networking.** Each service name is a hostname on a private network. From the `app` container, Postgres is `db:5432`. From the WSL terminal, it's `localhost:5433` through the port mapping. `localhost` inside a container means *that container*.

**Named volume vs bind mount.**
- `pgdata:/var/lib/postgresql/data` — named volume, Docker-managed, survives `compose down`. Persistence.
- `./app:/code/app` — bind mount, your source folder mapped in. With `--reload`, edits are live. Development convenience.

**`depends_on` with `condition: service_healthy`** — waits for the healthcheck, not just container start. Postgres takes seconds to initialise; plain `depends_on` lets the app crash into a database that isn't accepting connections yet.

**Postgres image env vars** (`POSTGRES_USER` etc.) are read on **first start only**. Changing them later does nothing until `docker compose down -v` resets the volume.

**Alpine.** `redis:7-alpine` is fine (no deps). Not for Python: compiled wheels target glibc; Alpine uses musl; pip falls back to building from source.

---

## 10. Alembic

`alembic init` → `env.py` edited to read `sqlalchemy.url` from `get_settings()` (one source of truth for the DB URL) and set `target_metadata = Base.metadata` (what autogenerate diffs against).

`from app.models import Base` works because `models/__init__.py` imports every model file. **If a model file isn't imported, Alembic doesn't know that table exists and silently omits it.** Most common cause of an empty autogenerated migration.

**Always read the migration before `upgrade head`.** Autogenerate misses some things (server-default changes, some constraints) and occasionally gets a type wrong. The migration file is what runs; the models are just its input. Verified today with `grep -c` for `ondelete` (5), `CheckConstraint` (4), `timezone=True` (8).

`alembic upgrade head` creates `alembic_version` to track what's applied, then runs `upgrade()`.

---

## 11. `/health`

- `SELECT 1` — cheapest query that proves pool, credentials, and network work.
- `socket_connect_timeout=1` on Redis — a down Redis must not make `/health` hang for the OS TCP timeout.
- Catch `SQLAlchemyError` / `RedisError` specifically, never bare `except:` — a typo in the handler should crash, not report as "database error."
- **Return `503` when degraded.** Load balancers read status codes, not JSON. `200 + "degraded"` keeps traffic flowing to a broken instance.

---

## 12. HTTP status codes used today and why

| Code | When | Why not the obvious alternative |
|---|---|---|
| `202 Accepted` | Upload / ticket submit returns before background work | `201 Created` claims the thing is ready. It isn't. |
| `401 Unauthorized` | No/invalid token | "I don't know who you are." |
| `403 Forbidden` | Valid token, wrong role | "I know exactly who you are, and no." |
| `409 Conflict` | Duplicate document hash | Request is valid; it conflicts with current state. |
| `422 Unprocessable Entity` | Pydantic validation fails | FastAPI returns this automatically. |
| `503 Service Unavailable` | `/health` degraded | Machines read this; `200` would route traffic to a broken instance. |

---

## 13. Failure-mode principles (from the design pass)

1. **Persist the input before doing anything that can fail.** Ticket row before the LLM. Citations before the draft.
2. **Degrade to the human.** Every failure path ends with an agent looking at it.
3. **Make stuck states visible** (status columns, metrics) rather than building recovery you can't maintain.

`BackgroundTasks` are in-process and not durable. Say so. "At scale this moves to Celery/RQ; the ingestion function doesn't change, only what invokes it."

---

## 14. Habits adopted today

- Run every command from the project root. Git, pip, Compose, Alembic, uvicorn all resolve config relative to cwd.
- `git status` before `git add .`. Check `.env` is absent.
- Save All before running anything. The editor shows the buffer; Python reads the disk.
- Run one command, answer its prompts, then the next. Never paste a block into an interactive prompt.
- Read the migration before applying it.

---

## 15. Interview questions I can now answer

- What does `Depends` do? Why is the DB session a dependency rather than a global?
- What's the difference between a Pydantic schema and a SQLAlchemy model, and why have both?
- Why UUID primary keys? What's the downside?
- Why `VARCHAR` + check constraint instead of a native enum?
- What's the difference between `depends_on` and `depends_on` with `condition: service_healthy`?
- Why does `localhost` not work from inside a container?
- Why should a health endpoint return `503`?
- What does `ON DELETE CASCADE` do and when is it wrong?
- Why `202` instead of `201`?
- What's the difference between `401` and `403`?

## 16. What I have not done and should not claim

- No durable task queue (no Celery).
- No embeddings, no vector search yet.
- No auth yet — that's Day 2.
- Not deployed — that's Day 5.
