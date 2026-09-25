# Progress Log — AI Support Triage API

---

## Day 0 — Environment setup

**Date:** 11 Sep 2026

### Built

- WSL2 + Ubuntu 26.04 (codename `resolute`) established as the development environment
- Docker Engine 29.8.0 + Compose v2 installed natively inside WSL (not Docker Desktop)
- Non-root Docker access configured via `usermod -aG docker`, verified with `hello-world`
- Python virtualenv created at `~/projects/ai-support-triage/.venv`
- Git repository initialised; `.gitignore` written *before* any secret file existed
- SSH keypair (ed25519) generated and registered with GitHub
- Two commits pushed to `github.com/Aman-srivastav24/ai-support-triage`
- VS Code connected to WSL — files, terminal and interpreter all on the Linux side
- Accounts created: GitHub repo, Groq API key, Neon Postgres project (Singapore, free tier)

### What broke

**1. `apt` failing against `security.ubuntu.com`**
Errors read `Cannot initiate the connection ... (101: Network is unreachable)` against
addresses like `2620:2d:4000:1::103`. Those are IPv6. WSL2 had no working IPv6 route, so
apt attempted IPv6 first, waited for the timeout, then fell back to IPv4 — repeatedly,
for every index file.
Fixed with `Acquire::ForceIPv4 "true";` in `/etc/apt/apt.conf.d/99force-ipv4`.
Result: all warnings cleared on the next `apt-get update`.

**2. `python3.12` not available**
`E: Unable to locate package python3.12`. Ubuntu 26.04 ships only Python 3.14; distro
archives do not carry older Python versions.
Resolved by changing the decision rather than the environment — see below.

**3. `ensurepip is not available`**
`python3 -m venv .venv` failed on a fresh Ubuntu. Debian/Ubuntu unbundle `venv` and
`pip` from the base Python package, unlike upstream Python.
Fixed with `sudo apt-get install python3.14-venv`.

**4. Pasted a multi-command block into an interactive prompt**
Ran `ssh-keygen` and pasted the follow-up `cat` command at the same time. `ssh-keygen`
consumed the second line as the answer to "Enter file in which to save the key" and
tried to create a key at a path that did not exist.
Lesson: interactive prompts read whatever is queued in stdin, including pasted text.
Run one command, answer its prompts, then run the next.

### Decisions

**Python 3.14, not 3.12 (deviation from the plan document)**
Ubuntu 26.04 ships only 3.14. Rather than install an older Python from a third-party
PPA, tested the four dependencies that contain compiled extensions — `pydantic-core`
(Rust), `psycopg` (C), `sqlalchemy` (optional C extensions), `tiktoken` (Rust). All
installed from prebuilt wheels with no source builds, so 3.14 is viable.
The Dockerfile will pin `python:3.14-slim` so local and container agree.
Position: *the container is the source of truth for runtime version; the local machine
only has to match it.*

**Docker Engine in WSL2, not Docker Desktop**
Fewer moving parts, no Windows/Linux file-sharing layer, and the container runtime sits
on the same side as the source code.

**Project on the Linux filesystem (`~/projects/`), not `/mnt/c/`**
Files under `/mnt/c` are reached across the Windows–Linux boundary over a network-style
protocol. Slow for `pip install`, worse for Docker bind mounts, and permissions behave
inconsistently.

**Neon Auth disabled**
Managed auth would remove the entire Day 2 build — JWT, bcrypt, `get_current_user`,
RBAC. Those are the most-interviewed backend topics in this project.

**Neon over Render Postgres**
Render's free Postgres is deleted after 30 days; Neon's free-tier data is
permanent. *Corrected on Day 5:* the compute is not always on. It scales to
zero after 5 minutes idle (fixed on the free plan) and wakes on the next query
in a few hundred milliseconds. `pool_pre_ping=True` (Day 1) is what makes the
dropped connections harmless.

**SSH over HTTPS + token for GitHub auth**
No token expiry to manage, and it matches what most workplaces use.

### Numbers

| Metric | Value |
|---|---|
| apt download throughput | ~5 KB/s — network is slow, budget extra time for image pulls |
| Docker Engine version | 29.8.0 |
| Python version | 3.14.4 |
| Neon free tier | 100 CU-hrs, 0.5 GB storage, 5 GB transfer/month |

### Open items

- Confirm Python extension installed on the WSL side of VS Code
- Groq has no embeddings endpoint — Day 3 will need a second provider for embeddings.
  Decide on Day 3, not before.

  ## Day 1 — Backend spine

**Date:** 13 Sep 2026

### Built

- `docs/ARCHITECTURE.md` — data model with columns, three request flows as
  sequence diagrams, data-flow diagram, seven failure modes with decisions,
  decision/alternative table. Six Mermaid diagrams rendering on GitHub.
- Layered package layout: `app/api`, `core`, `db`, `models`, `schemas`, `services`
- `pyproject.toml` with pinned-minimum dependencies, `[dev]` extras, editable install
- `app/core/config.py` — `pydantic-settings`, `.env` locally, env vars in containers
- `Dockerfile` (`python:3.14-slim`), `.dockerignore`, `docker-compose.yml`
  (app + `pgvector/pgvector:pg16` + `redis:7-alpine`) with healthchecks and
  `depends_on: service_healthy`
- `app/db/session.py` — engine with `pool_pre_ping`, session factory, `get_db` dependency
- Five SQLAlchemy 2.0 models: `User`, `Document`, `Chunk`, `Ticket`, `TicketCitation`
  with UUID PKs, `TIMESTAMPTZ`, named check constraints, explicit `ON DELETE` rules
- Alembic wired to `Base.metadata` and app settings; first migration reviewed and applied
- `GET /health` checking Postgres and Redis, returning 503 when degraded
- Full stack up under Compose; `/health` green from inside the container

### What broke

**1. `ImportError: cannot import name 'Chunk'`**
File existed, class was visible in the editor, Python couldn't find it. Unsaved
VS Code buffer — the file on disk was empty. Save All, re-run, fixed.
Lesson: the editor shows the buffer; Python reads the disk.

**2. VS Code Server re-download on `code .`**
Windows VS Code had updated, so the Linux-side server had to match. One-time per
update, not per launch. Also opened `docs/` as workspace root by running `code .`
from the wrong directory — reopened from project root.

**3. `grep: .gitignore: No such file or directory`**
Ran from `app/core/`. Git, pip, Compose, Alembic, uvicorn all resolve config
relative to the current directory. Rule adopted: run everything from project root.

**4. Port collision risk with Windows Postgres 18.1**
A separate Postgres already listens on 5432 on the Windows side. Mapped the
container to `5433:5432` on the host rather than uninstalling. Windows install
left in place, unused.

### Decisions

**`pgvector/pgvector:pg16` instead of `postgres:16`**
Same Postgres 16, pgvector extension precompiled. Day 3 becomes
`CREATE EXTENSION vector` in a migration rather than an image swap and volume reset.

**`pydantic-settings` pulled forward from Day 5**
Needed `DATABASE_URL` from env on Day 1. `database_url` has no default so the app
refuses to start unconfigured; `redis_url` has a default because Redis is non-critical.

**`VARCHAR` + named `CheckConstraint` over Postgres `ENUM`**
`ALTER TYPE` is awkward inside Alembic's transaction; removing enum values is
near-impossible. Ticket statuses change on Days 4 and 10. Python `StrEnum` carries
the type safety; the DB constraint carries the guarantee.

**Python-side `uuid.uuid4` default, not `gen_random_uuid()`**
ID is known before flush, which Flows A and B need for scheduling background work
and returning the ID. Deviation from ARCHITECTURE.md noted there.

**`/health` returns 503 when degraded**
Load balancers read status codes, not JSON bodies. `200 + "degraded"` would keep
traffic flowing to a broken instance.

**Two `DATABASE_URL`s, one database**
`.env` → `localhost:5433` (host, through port mapping). Compose `environment` →
`db:5432` (container-to-container over the Compose network). `localhost` inside a
container is that container.

**No `embedding` column yet**
Deferred to Day 3 so the migration there teaches adding an extension and an
indexed column to a populated table — the migration you write at work.

### Numbers

| Metric | Value |
|---|---|
| Image build (first, with `pip install`) | 18.0 s total, 14.0 s in pip |
| Postgres in container | 16.15 |
| Tables / indexes / FKs / check constraints | 5 / 4 / 5 / 4 |
| Migration revision | `d6928171bf12` |
| `/health` under Compose | `{"status":"ok","checks":{"database":"ok","redis":"ok"}}` |

### Open items

- Windows Postgres 18.1 still installed and running; harmless, could be removed
- `alembic.ini` `sqlalchemy.url` line removed — confirm it's not in the commit
- Day 2: JWT + bcrypt + `get_current_user`; document upload with chunking as a
  background task. Chunking needs a tokenizer — `tiktoken` already verified on 3.14.

  ## Day 2 — Auth and ingestion

**Date:** 16 Sep 2026

### Built

- `app/core/security.py` — bcrypt hashing (cost 12), JWT mint/verify with PyJWT,
  custom `TokenError`. Only module importing `bcrypt` or `jwt`.
- `app/core/config.py` — added `jwt_secret_key` (no default), `jwt_algorithm`,
  `jwt_expiry_minutes`
- `app/schemas/user.py` — `UserRegister`, `UserRead`, `Token`
- `app/services/auth.py` — `create_user`, `authenticate_user`, `get_user_by_email`;
  `EmailAlreadyRegistered`, `InvalidCredentials`
- `app/api/deps.py` — `get_current_user`, `require_admin`, and the `DbSession` /
  `CurrentUser` / `AdminUser` Annotated aliases
- `app/api/auth.py` — `POST /auth/register` (201), `POST /auth/login` (200),
  `GET /auth/me`
- `app/services/chunking.py` — `chunk_text` with tiktoken, 500-token windows,
  50-token overlap, frozen `TextChunk` dataclass
- `app/services/documents.py` — `create_document` (SHA-256 dedup) and
  `ingest_document` (own session, pending → processing → ready/failed)
- `app/schemas/document.py` — `DocumentRead`, excluding `raw_text` and `content_sha256`
- `app/api/documents.py` — `POST /documents` (202, admin only, background task),
  `GET /documents/{id}`
- No model or migration changes — Day 1's `User`, `Document` and `Chunk` already
  carried every column auth and ingestion needed

### What broke

**1. Container died on startup: `jwt_secret_key Field required`**
`.env` had the key; the container didn't. `.dockerignore` excludes `.env` (correctly —
secrets must not be baked into an image), so the container only sees what Compose's
`environment:` block passes it. Fixed with
`JWT_SECRET_KEY: ${JWT_SECRET_KEY:?JWT_SECRET_KEY is not set}` — Compose substitutes
from the host `.env` and refuses to start if it's missing.
Rule: every new setting goes in two places — `.env` for local, Compose `environment:`
for the container.

**2. `ModuleNotFoundError: No module named 'tiktoken'`**
Installed into the venv on Day 0 during the Python 3.14 compatibility check, never
declared in `pyproject.toml`. The venv accumulates whatever you've ever installed;
the image is built only from what's declared. Textbook "works on my machine".
Fixed by adding `tiktoken>=0.8` and rebuilding.

**3. `http://localhost:8000` unreachable from the Windows browser**
The app was healthy — `curl` from inside WSL returned 200. Windows resolves
`localhost` to IPv6 `::1` first, and WSL2's port forwarding only listens on IPv4.
Use `http://127.0.0.1:8000`. Same root cause family as the Day 0 apt IPv6 failure.

**4. `Could not validate credentials` on a curl request**
`$TOKEN` was never set in that shell — the upload had been done through `/docs`,
which holds its own token. Not a bug: the flat 401 message is deliberate and gives
no hint whether the token was missing, expired or forged.

### Decisions

**`bcrypt` directly, not `passlib`**
`passlib`'s last release was 2020 and it breaks against modern bcrypt (reaches for
`bcrypt.__about__.__version__`, removed upstream). Same reasoning for `pyjwt` over
`python-jose` — the latter is barely maintained and has had CVEs.

**`get_current_user` hits the database on every request**
The token already carries `sub` and `role`, so the lookup is skippable. Kept it
because it's what makes `is_active` and role changes take effect immediately rather
than at token expiry. Cost: one indexed primary-key read per request.
Verified live — promoting a user to admin worked with their existing agent-role token.
Corollary: the `role` claim in the JWT is for frontend display only. Authorisation
reads the database.

**60-minute token expiry**
JWTs can't be revoked before expiry, so lifetime is the worst-case exposure window.
60 min balances that against re-login friction. `is_active` covers the urgent case.

**Timing-attack defence on login**
An unknown email returns in ~1ms while a wrong password costs a bcrypt hash (~360ms).
That gap leaks which emails have accounts (user enumeration). Unknown emails are now
hashed against a dummy bcrypt string so both paths cost the same.
All three failure modes — no such user, wrong password, deactivated — raise the same
`InvalidCredentials` and return the same message.

**Known gap: `POST /auth/register` returns 409 on a duplicate email**, which does leak
account existence. The production fix is to respond identically and resolve it over
email; that needs email infrastructure this project doesn't have.

**Two-layer duplicate protection, twice**
Both unique email and unique `content_sha256` use a Python pre-check for a readable
error *plus* an `IntegrityError` catch for the race between check and insert. The
database constraint is what guarantees correctness; the Python check is for UX.
`db.rollback()` before re-raising — after an `IntegrityError` Postgres rejects every
further statement on that connection until the transaction is rolled back.

**Layer boundaries held**
`core` and `services` raise our own exceptions (`TokenError`, `InvalidCredentials`,
`DuplicateDocument`) and know nothing about HTTP. `api` is the only layer that
converts them to status codes. Every service was tested directly from a Python
script with no web server involved.

**`Annotated` dependency aliases over `= Depends(...)`**
`admin: AdminUser` puts the security requirement in the signature where a reviewer
sees it, instead of in the function body where it can be deleted by accident.

**202 Accepted for upload, not 201**
201 would claim the document is ready; chunking hasn't started when the response is
sent. 202 + a `status` field + `GET /documents/{id}` is the polling contract.

**`BackgroundTasks`, not Celery**
One admin, a handful of uploads, 14-day scope. Built the queue-shaped contract anyway
— status column, immediate ID return, polling endpoint — so swapping in a real queue
later changes the executor, not the API. Accepted limits: no retry, no supervision,
work lost on process death, shares the API process.
Mitigation: `ingest_document` catches every exception, writes `status = failed` and
stores the reason in `error_message`, which `DocumentRead` exposes.

**Background tasks take IDs, not ORM objects**
The request's session is closed by the time the task runs, so `ingest_document(uuid)`
opens its own `SessionLocal()` and closes it in `finally`. Passing the `Document`
object would raise on every attribute access; forgetting the `finally` would leak a
connection per upload until the pool is exhausted.

**`tiktoken` `cl100k_base` for chunk sizing**
Not the exact tokenizer for Groq or Gemini, so counts are approximate — acceptable
for sizing chunks. For real cost tracking (Day 11), use the token counts the provider
returns in its response rather than a local estimate.

**Fixed-size chunks, not structure-aware**
Splitting purely on token count ignores paragraph and section boundaries. The next
improvement is splitting on structure first and falling back to hard cuts. Out of
scope for 14 days; chunk size gets tuned against the eval set on Day 7.

**Content-type validation is a convenience, not a control**
`content_type` is client-supplied and trivially forged. What actually rejects a
binary is the UTF-8 decode. The 5MB cap also runs *after* `await file.read()`, so
a hostile client could still pressure memory — the real fix is a body-size limit at
the reverse proxy. Day 12.

**Sync SQLAlchemy inside `async def upload_document`**
Blocking DB calls on the event loop. Brief enough not to matter at this scale; the
correct fix is `asyncpg` + `AsyncSession` throughout, which is a day-one decision
rather than a retrofit.

### Numbers

| Metric | Value |
|---|---|
| bcrypt cost factor | 12 |
| bcrypt hash time (this machine) | 0.36 s |
| Login — wrong password | 0.362 s |
| Login — unknown email | 0.356 s (6 ms gap; enumeration defence holding) |
| JWT expiry | 60 min |
| Chunk size / overlap | 500 / 50 tokens (step 450) |
| Chunking test: 2001 tokens | 5 chunks, last one 201 tokens |
| policy.txt ingestion | 4 chunks, pending → ready |
| Upload size cap | 5 MB |

### API surface after Day 2

| Method | Path | Auth | Success |
|---|---|---|---|
| GET | `/health` | none | 200 |
| POST | `/auth/register` | none | 201 |
| POST | `/auth/login` | none | 200 |
| GET | `/auth/me` | any user | 200 |
| POST | `/documents` | admin | 202 |
| GET | `/documents/{id}` | admin | 200 |

Verified: `/auth/me` 401 before login, 200 after · duplicate upload 409 ·
agent uploading 403 · tampered token 401

### Files and what's in them

- `app/core/config.py` — `Settings`, `get_settings()` (`@lru_cache`)
- `app/core/security.py` — `hash_password`, `verify_password`,
  `create_access_token`, `decode_access_token`, `TokenError`
- `app/db/session.py` — `engine`, `SessionLocal`, `get_db`
- `app/models/` — `User` + `UserRole`, `Document` + `DocumentStatus`, `Chunk`,
  `Ticket`, `TicketCitation`
- `app/schemas/user.py` — `UserRegister`, `UserRead`, `Token`
- `app/schemas/document.py` — `DocumentRead`
- `app/services/auth.py` — `create_user`, `authenticate_user`, `get_user_by_email`
- `app/services/chunking.py` — `chunk_text`, `count_tokens`, `TextChunk`
- `app/services/documents.py` — `create_document`, `ingest_document`
- `app/api/deps.py` — `DbSession`, `CurrentUser`, `AdminUser`, `get_current_user`,
  `require_admin`
- `app/api/auth.py`, `app/api/documents.py`, `app/api/health.py` — routers
- `app/main.py` — mounts health, auth, documents routers

### Open items

- `get_document` in `app/api/documents.py` has imports inside the function body —
  move them to module level
- No `GET /documents` list endpoint yet; only fetch-by-id
- No admin-creation path — admins are promoted with SQL. Fine for now; a seed
  script or an admin-only `PATCH /users/{id}/role` would be the real fix
- `app/db/session.py` calls `get_settings()` at module level, which bypasses the
  dependency-override hook. Will need addressing for Day 5 tests
- Day 3: pgvector extension, `embedding` column on `Chunk`, embeddings during
  ingestion, similarity search, grounded prompt — then break it on purpose and
  record the hallucination

  ## Day 3 — RAG core

**Date:** 18 Sep 2026

### Built

- `app/services/embeddings.py` — Gemini `embedContent` via httpx, `EmbeddingError`,
  30s timeout, dimension assertion, L2 normalisation. Only module knowing the
  embedding provider.
- Migration `a2cc4598a7c9` — `CREATE EXTENSION IF NOT EXISTS vector`, nullable
  `embedding vector(768)` on `chunks`, HNSW index with `vector_cosine_ops`
- `Chunk.embedding` via `pgvector.sqlalchemy.Vector(768)`
- `ingest_document` now embeds each chunk before insert, logs per-chunk progress,
  single commit at the end so a partial failure leaves nothing behind
- `scripts/backfill_embeddings.py` — idempotent NULL-only backfill, commits every
  10 rows, skips individual failures. Written but never needed; test data was
  deleted instead.
- `app/services/retrieval.py` — `search_chunks`, cosine distance via `<=>`,
  returns frozen `RetrievedChunk` with similarity = 1 - distance
- `app/services/llm.py` — Groq chat completions, `LLMError`, 60s timeout,
  temperature 0.2, grounded system prompt
- `app/services/tickets.py` — `create_ticket` (commit immediately) and
  `process_ticket` (retrieve → filter → draft → store citations)
- `app/schemas/ticket.py` — `TicketCreate`, `CitationRead`, `TicketRead`
- `app/api/tickets.py` — `POST /tickets`, public, 201
- `sample_docs/` — billing, troubleshooting, accounts. Written to contain
  specific numbers, error codes, deliberate gaps, and a 14-day vs 30-day
  refund collision.
- `scripts/test_embeddings.py`, `test_retrieval.py`, `test_llm.py`

### What broke

**1. Gemini vectors are not unit length at reduced dimensions**
Magnitude came back 0.5898, not 1.0. Gemini normalises its default 3072-dim
output; truncating to 768 via `outputDimensionality` does not renormalise.
Caught by measuring instead of assuming. Fixed with `_normalise` in the service
so every stored vector is unit length. Similarity scores were identical to four
decimal places before and after — normalising changes length, not direction.
Matters because cosine-equals-dot-product only holds for unit vectors, and half
the reference material assumes it.

**2. Alembic autogenerate produced a file that could not run**
It detected the column but wrote `pgvector.sqlalchemy.vector.VECTOR(dim=768)`
with no corresponding import — `NameError` on apply. It also cannot see
extensions or vector indexes at all. Rewrote `upgrade()` by hand.
Autogenerate is a draft, not an answer.

**3. `httpx` was a dev-only dependency**
Declared under `[project.optional-dependencies] dev` because it arrived with
FastAPI's TestClient. Application code now imports it at runtime, so it had to
move to the main list. Caught before it reached the container — the same class
of failure as Day 2's `tiktoken`.

**4. Groq model `llama-3.3-70b-versatile` returned 404**
Model retired. 404 not 401 is the tell: the key authenticated, the path didn't
resolve. Listed available models via `GET /openai/v1/models` and switched to
`openai/gpt-oss-20b`. One-line change because the model name lives in config,
not in `llm.py`.

**5. Test corpus was one paragraph repeated**
`policy.txt` and `refunds.txt` were the same refund sentence copy-pasted to
length — 8 chunks, all near-identical embeddings, retrieval untestable. Also
revealed SHA-256 dedup is exact-match only; the two files differed by a byte.
Deleted both; `ON DELETE CASCADE` removed the chunks automatically.

**6. Shell word-splitting in `test_llm.py`**
`python scripts/test_llm.py please tell me about refund policy` passed only
`please` — the shell split on spaces and `sys.argv[1]` is one word.
Fixed with `" ".join(sys.argv[1:])`.

### The hallucination (Day 3's required experiment)

Question: *"Do you offer a student discount, and how do I apply for it?"*
Retrieval: Billing at 0.5756. No student discount exists anywhere in the corpus.

**Naive prompt** ("You are a helpful customer support assistant"):

> I'm afraid we don't have a dedicated student discount at the moment. All of our
> plans are priced as listed (Starter $12 / month, Team $49 / month, Business
> $199 / month) with the 20 % annual-billing discount available on the Team and
> Business tiers.
>
> If you believe you might qualify for a special rate or have a unique situation,
> you can reach out to our billing team at billing@example.com. They'll review
> your request and let you know if any additional discounts can be applied.

Prices, the annual discount and the email address are all correct. The invented
part is the **process**: the corpus says `billing@` is for refund requests with an
invoice number. There is no discount review. "at the moment" also implies a
roadmap it has no knowledge of.

The dangerous failure was not a fabricated fact but a fabricated process appended
to an otherwise accurate answer — which survives a skim review, unlike an obviously
wrong number.

**Grounded prompt**, same question, same chunks, same model:

> The documentation does not cover this.

Verified grounding did not overcorrect:

| Case | Result |
|---|---|
| Fully answerable (refund window) | "within 14 days of the first charge… renewal charges are not refundable" |
| Not answerable (student discount) | exact refusal sentence |
| Partially answerable (BIL-409 + how to update card) | gave the code, stated the rest is not covered |

The grounded answer to the refund question was also *tighter* than the naive one,
which had added an inference the document does not make.

### Decisions

**Gemini for embeddings, Groq for generation**
Groq has no embeddings endpoint, so a second provider was unavoidable (flagged as
a Day 0 open item). Alternative considered: `sentence-transformers` locally — no
API dependency, works offline, but pulls PyTorch (~2 GB) into the image, which is
a bad trade on Day 5 deployment and Render's free tier. Rejected on image size.
Accepted cost: ingestion and the ticket path both depend on an external service.

**768 dimensions, not the default 3072**
pgvector's HNSW index caps at 2000 dimensions, so 3072 could not be indexed on a
`vector` column. 768 is one of Google's recommended MRL sizes and stores at ~3 KB
per chunk instead of ~12 KB.

**HNSW, not IVFFlat**
HNSW builds on an empty table and gives better recall; IVFFlat needs
representative data present before the index is built. Chunks arrive over time,
so IVFFlat would have to be rebuilt.

**`vector_cosine_ops` is a contract, not a detail**
The index is only used if queries use the matching operator. Querying with L2
would silently seq-scan with no error.

**Nullable column, then backfill**
Standard three-step for adding a column to a populated table: add nullable,
backfill, optionally tighten. `NOT NULL` would have required inventing a vector
for existing rows, and a zero vector is a lie that poisons search.

**No `DROP EXTENSION` in downgrade**
Extensions are database-wide shared state. Another table may depend on it by then.

**Single commit in ingestion, periodic commits in backfill**
Opposite rules for opposite goals. A half-ingested document is a broken state —
searches find some of it and silently miss the rest — so it is all-or-nothing.
A half-completed backfill is genuine progress, and the NULL filter makes a
restart resume cleanly.

**`SIMILARITY_FLOOR = 0.55` is a junk filter, not a correctness check**
Set just above the unrelated-question ceiling of 0.525. It cannot separate
answerable from unanswerable because those bands overlap (below). Grounding and
human review do that job.

**`customer_email` is `str`, not `EmailStr`**
A typo in an email should not block a support ticket from reaching a human.
Contrast `UserRegister`, where the email is the login identity and strictness is
correct. Validate strictly where wrong data breaks something.

**201 on `/tickets`, 202 on `/documents`**
Processing completes before the ticket response is sent, so the resource exists
in full. If Day 4 backgrounds it, this becomes 202 plus a polling endpoint —
the contract uploads already use.

**502 for LLM failure, 500 for everything else**
502 means the dependency failed, not the service, and suggests a retry may help.
Both messages state the ticket *was* received, which is true: `create_ticket`
commits before processing.

### Numbers

| Metric | Value |
|---|---|
| Embedding model / dimensions | `gemini-embedding-001` / 768 |
| Vector magnitude before / after normalisation | 0.5898 / 1.000000 |
| Embedding latency (single call) | 0.6 – 1.9 s, ~1.1 s typical |
| Retrieval latency, median | ~0.7 s, dominated by the embedding call |
| Generation latency (`openai/gpt-oss-20b`) | 0.65 – 1.95 s, ~0.8 s typical |
| End-to-end, retrieve + draft | ~1.5 s |
| **Top-1 retrieval accuracy, in-corpus** | **5 / 5** |
| In-corpus top-score range | 0.587 – 0.656 |
| Not-in-corpus top-score range | 0.586 – 0.605 |
| Unrelated top-score range | 0.515 – 0.525 |
| Similarity floor chosen | 0.55 |
| Documents / chunks | 3 / 3 |

**The finding that matters most:** the in-corpus and not-in-corpus bands overlap.
The worst legitimate question ("How long does delivery to the UK take?", 0.5865)
scored *lower* than two questions the corpus cannot answer — student discount
0.5965 and phone number 0.6053. The single word "please" scored 0.6093.
No threshold separates answerable from unanswerable. Similarity measures topic,
not whether a specific fact is present. This is why a threshold alone is not
grounding, and why the design needs the grounded prompt, citations and a human
reviewer as well.

### API surface after Day 3

| Method | Path | Auth | Success |
|---|---|---|---|
| POST | `/tickets` | none (public) | 201 |

### Open items

- **`POST /tickets` has not been called yet** — code compiles and the container is
  healthy, nothing more. Verify before claiming it works.
- Each sample document produces exactly 1 chunk (all under 500 tokens), so chunk
  overlap and mid-sentence cuts are not exercised, and "right chunk" is the same
  problem as "right document". Expand the corpus on Day 7.
- Ingestion embeds chunks serially with no retry and holds one transaction open
  for the whole run. Batching or concurrency is the obvious improvement.
- `POST /tickets` blocks ~1.5 s on two external calls, with sync SQLAlchemy on
  the event loop. Public and unrate-limited until Day 12.
- `used_in_reply` on `TicketCitation` is always false — retrieved is not the same
  as used. Day 10 reflection fills this in.
- `confidence` stays NULL and no ticket reaches `escalated`. Day 4.
- Groq retired a model mid-project; model name stays in config for this reason.
- Carried from Day 2: imports inside `get_document`; no `GET /documents` list;
  `session.py` calls `get_settings()` at module level.

  ## Day 4 — Agent, Redis, streaming

**Date:** 24 Sep 2026

### Built

- `app/schemas/classification.py` — `TicketCategory` StrEnum
  (billing/technical/account/other), `TicketClassification` model
- `classify_ticket()` in `llm.py` — Groq strict structured output, schema
  generated from the Pydantic model, temperature 0.0, returns OTHER on any
  failure rather than raising
- `app/graph/state.py` — `TriageState` TypedDict, nine fields, `total=False`
- `app/graph/nodes.py` — `classify`, `make_retrieve_node`, `draft`,
  `score_confidence`; `_build_query` shared by retrieve and draft
- `app/graph/triage.py` — `build_triage_graph(db)`, compiled per request,
  conditional edge on `escalate`, terminal nodes `escalate` / `return_draft`
- `app/services/cache.py` — the only module that knows Redis exists
- Caching in three places: query embeddings, classification, drafts
- `persist_result` and `mark_failed` extracted from `process_ticket` so the
  blocking and streaming paths share one persistence implementation
- `TicketAck` schema; `POST /tickets` now returns `{id, status}` only
- `POST /tickets/stream` — SSE, one event per node as it completes
- `logging.basicConfig` in `main.py`
- `scripts/test_classify.py`, `scripts/test_graph.py`, `scripts/strict_test.json`

### What broke

**1. `HTTP 000` read as a fast response — twice**
Timing runs returned 0.0003 s and looked like excellent performance. The app
wasn't running; the OS refused the connection instantly. `-s` hid the error
and `-o /dev/null` discarded the body.
Rule: every latency measurement prints `%{http_code}` alongside the time. A
fast failure always looks like a fast success.

**2. Header injection via a pasted newline**
A curl command had a line break inside the `Authorization` header value.
Groq returned `invalid character 'C' looking for beginning of value`. The
blank line separates headers from body in HTTP, so the stray newline ended
the header block early and `Content-Type: application/json` became the first
line of the body — hence the `'C'`.
Same class as SQL and prompt injection: untrusted content crossing into a
control channel. Fixed by putting request bodies in a file and using `-d @`.

**3. `pydantic-settings` found no `.env`**
Ran a script from `app/services/`. Four required settings failed validation.
Config is resolved relative to the working directory.
Day 1's rule extended: `pydantic-settings` joins git, pip, Compose, Alembic
and uvicorn on the list of things that must be run from project root.
The cache module degraded correctly — logged a warning, returned None,
nothing crashed.

**4. Node logs never reached the container**
`logger.info` in every node, nothing in `docker compose logs`. uvicorn
configures its own loggers but not the root logger, whose default level is
WARNING. Fixed with `logging.basicConfig` in `main.py`. Had been running
blind since the graph was written.

**5. Measured during a restart**
Chained `docker compose restart` and a timing run in one paste; curl fired
while the app was shutting down. `--reload` had already picked up the edit,
so the restart was unnecessary in the first place.
Rule: health check between any restart and any measurement.

**6. A node returning `{}` streams as `None`**
`result.update(changes)` raised `TypeError: 'NoneType' object is not
iterable` on the terminal node. LangGraph normalises "changed nothing" to
`None` in the stream, not to an empty dict. Fixed with `if changes:`.
The error path behaved correctly — client got an `error` event, traceback
was captured, no hang.

### Decisions

**No self-rated confidence from the model**
Considered asking the model for a 0–1 confidence alongside the category.
Rejected: self-reported confidence is poorly calibrated and is high exactly
when the model is fluently wrong — Day 3's fabricated refund process would
have scored itself high. Escalation is built from observable facts instead.
Would revisit as a measured experiment once the Day 6 eval set exists.

**Confidence is rule-based, and similarity is not the decider**
Escalates when any of: no chunks cleared the floor, the draft contains the
grounded refusal sentence, or the category is OTHER. Deterministic, no extra
API call. Day 3 measured the answerable and unanswerable similarity bands
overlapping, so no threshold can separate them — the strongest signal turned
out to be the model's own refusal sentence, which came free from grounding.
Catches absence of grounding; does not catch bad inference over good
grounding (the Day 3 "signed up last week" case). Day 10 reflection.

**Two tiers, not three**
Dropped the MEDIUM tier: it returned the draft exactly like HIGH, so the
label changed nothing. The numeric score is still stored for Day 6 analysis.
Would earn its place if a real agent queue sorted work by risk.

**Category does not filter retrieval**
Concrete reason: a ticket reporting error `BIL-409` on the billing page
classified as `technical`. Filtering retrieval by category would have
searched troubleshooting docs and missed the billing chunk that contains
the code. Classification is single-label and some tickets are genuinely
both.

**`classify_ticket` never raises**
Classification enriches a ticket; it does not gate one. An unclassified
ticket can still be retrieved for and drafted. Returns OTHER on failure and
logs a warning. Same stance as Day 1's `redis_url` having a default.

**Graph built per request, not at startup**
`make_retrieve_node(db)` closes over the request's session. A graph compiled
once at startup would hold the first request's session forever. Compiling is
cheap — wiring and validation, no I/O. The alternative is compiling once and
passing the session through LangGraph's per-invocation config, which is
cleaner at scale and more machinery to explain.

**Terminal nodes that return `{}`**
Both branches end the graph, so routing straight to END would work. Kept
named terminal nodes because the SSE stream then names the outcome as its
final event, the trace shows which path ran, and Days 10 and 12 have
somewhere to hang work. They return `{}` rather than writing a status field:
`escalate` already carries that fact, and duplicated state can disagree.

**`POST /tickets` returns `{id, status}` only**
The draft is written for an agent to review. A draft the customer has
already read is not a draft. Citations, document titles and similarity
scores are internal — exposing them on a public endpoint lets an anonymous
caller map the corpus by probing with crafted questions and reading the
score back. `TicketRead` kept, unused, for the agent endpoint on Day 5.

**Triage failure no longer returns 502**
Previously a drafting failure returned 502 with no ticket ID, so the caller
saw a failure and would resubmit a ticket that already existed. Now the
receipt is returned regardless: the ticket was stored and a human will see
it. Failures are visible in logs and in the row's status.

**Embedding caching is opt-in per call**
Ingestion embeds each chunk once and would never read the key back; ticket
queries repeat. The caller knows whether repetition is likely, the service
does not. `use_cache=False` by default.

**Cache keys carry everything that determines the value**
Embeddings: model + task type + dimensions. Gemini embeds a query
differently from a document, so serving one for the other would corrupt
results with no error anywhere. Classification: model. Drafts: model +
query + sorted chunk IDs.

**Only the draft cache has a TTL**
Embeddings and classifications are pure functions of their inputs, and every
input is in the key. Drafts depend on the corpus, which changes on upload.
Chunk IDs in the key catch a different retrieval; the 300 s TTL catches an
edit that keeps the same chunks. 300 s is a starting point, not a derived
value — it would be tuned against how often documents actually change.

**Cache failures are never fatal**
Every operation in `cache.py` swallows exceptions and returns None, so a
Redis outage and a cache miss are indistinguishable to callers. Slower,
still correct.

**Never cache a fallback**
`set_json` for classification sits outside the `try`. Caching the OTHER
fallback after a network blip would make that ticket text permanently
miscategorised.

**SSE, not WebSockets**
Traffic is one-directional: the client submits and then only listens. SSE is
plain HTTP, works through proxies, reconnects automatically. WebSockets
would add a return channel never used.

**Streaming is a separate endpoint**
A client wanting a JSON receipt should not have to parse an event stream.

**`_progress_event` is a whitelist**
Names exactly which fields leave, per node. A blacklist breaks the day
someone adds a field.

### Numbers

| Phase | Mean | External calls |
|---|---|---|
| Day 3 pipeline (pre-graph) | 1.48 s | 2 |
| With graph, no cache | 2.04 s | 3 |
| + embedding cached | 1.05 – 1.51 s | 2 |
| + classification cached | 0.60 s | 1 |
| + draft cached | **0.062 s** | 0 |

**2.04 s → 0.062 s, a 33× speedup — best case only.**

Per-stage, cold request:

| Stage | Cold | Warm |
|---|---|---|
| Classify (Groq) | ~0.45 s | 0.002 s |
| Embedding (Gemini) | 0.57 – 0.89 s | 0.002 s |
| Vector search (pgvector) | 0.017 s | 0.005 s |
| Draft (Groq) | 0.35 – 0.69 s | 0.557 s |

~95 % of cold latency is external API calls. The database is under 1 %.
Provider variance is large: the same request measured 0.57 s and 0.89 s for
the embedding, 0.35 s and 0.69 s for the draft. Quote ranges, not points.

Classification cost: 195 prompt + 97 completion tokens, of which 78 were
reasoning. `gpt-oss-20b` is a reasoning model, so 80 % of the output tokens
were thinking to produce a 5-token answer. Groq `queue_time` 0.315 s against
`total_time` 0.118 s — on free tier, queueing dominates.

Graph results, three tickets:

| Ticket | Category | Chunks | Confidence | Escalated |
|---|---|---|---|---|
| Refund window | billing | 2 | 0.6572 | no |
| Student discount | billing | 2 | 0.5874 | yes — refusal sentence |
| Sunday hours | other | 3 | 0.5672 | yes — refusal + other |

The student-discount ticket scored 0.5874, above the 0.55 floor, on a
question the corpus cannot answer. It escalated on the refusal sentence,
which has nothing to do with the score. Day 3's band overlap, reproduced.

**Also measured:** including the subject in the query, not just the body,
changed the draft for "Refund window" from `14 days.` to
`Refunds are available within 14 days of the first charge on a new
subscription. Renewal charges are not refundable.` Same model, same prompt,
same chunks. The terse answer had looked like a prompt problem; the input
was impoverished. Check what you are sending before tuning a prompt.

### API surface after Day 4

| Method | Path | Auth | Success | Returns |
|---|---|---|---|---|
| POST | `/tickets` | none | 201 | `{id, status}` |
| POST | `/tickets/stream` | none | 200 | SSE progress events |

Stream events, in order: `received`, `classified`, `retrieved`, `drafted`,
`scored`, then `escalate` or `return_draft`, then `done`.

### Open items

- **33× is best case only.** Requires identical text within the TTL. Real
  traffic repeats questions with different wording, which an exact-text hash
  misses entirely. Hit rate unmeasured — needs `/metrics` on Day 11. Semantic
  caching (matching on embedding similarity) would catch rephrasing, but
  needs the embedding first, so it saves only the generation call.
- `reasoning_effort: low` untested for classification. 80 % of output tokens
  were reasoning for a four-way choice. Day 11.
- A ticket classified OTHER still runs retrieve and draft before escalating —
  three API calls to reach a conclusion `classify` had at step one. Early exit
  would save two calls per off-topic ticket. Day 11.
- Classification is single-label. The BIL-409 ticket was genuinely both
  technical and billing. Multi-label is the real fix; out of scope.
- `docker-compose.yml` hardcodes `POSTGRES_PASSWORD: triage` and is committed.
  Should use env substitution like `JWT_SECRET_KEY` does. Day 12.
- httpx logs every request at INFO now. Useful for timing, noisy later.
  Silence on Day 11 when structured logging arrives.
- Drafts are cached despite `temperature: 0.2`, so identical questions get
  byte-identical answers for 300 s. A behaviour change, not only a speed one.
- Carried from Day 3: each sample doc is 1 chunk, so overlap and mid-sentence
  cuts are untested; `used_in_reply` always false; ingestion embeds serially.
- Carried from Day 2: imports inside `get_document`; no `GET /documents` list;
  `session.py` calls `get_settings()` at module level, which blocks the
  dependency-override hook needed for Day 5 tests.
- No agent-facing endpoint yet. `TicketRead` exists but nothing serves it, so
  nothing can currently read a draft. Day 5.

  ## Day 5 (part 1) — Testability refactor and test suite

**Date:** 24 Sep 2026

### Built

- `app/services/providers.py` — `LLMClient` and `Embedder` Protocols, `GroqLLM`
  and `GeminiEmbedder` as thin wrappers over the existing functions, `get_llm`
  and `get_embedder` dependencies. No prompt, caching or error-handling logic
  moved.
- `LLMProvider` / `EmbeddingProvider` Annotated aliases in `app/api/deps.py`
- Providers threaded through every layer: routes → `process_ticket` →
  `build_triage_graph(db, *, llm, embedder)` → node factories
  (`make_classify_node`, `make_retrieve_node`, `make_draft_node`) →
  `search_chunks(..., embedder=)`. Upload route passes the embedder into the
  `ingest_document` background task.
- `get_document` imports moved to module level (Day 2 open item)
- `scripts/test_graph.py`, `test_retrieval.py`, `test_llm.py` updated;
  `scripts/test_ticket_flow.py` deleted (unfinished, did not parse, duplicated
  `test_retrieval.py`)
- `triage_test` database, schema built with `alembic upgrade head`
- `[tool.pytest.ini_options] testpaths = ["tests"]`
- `tests/conftest.py` — test env set before app import, safety guard,
  `FakeEmbedder` (feature hashing), `FakeLLM` (scripted, records calls),
  `clean_state`, `client`, `agent_headers`, `admin_headers`
- 20 tests: fake embedder (5), health (1), auth (6), documents (4), tickets (4)
- Commits: `fd2f7f7` refactor, `796a70f` tests

### What broke

**1. The plan's testing approach did not fit the code**
"Use `dependency_overrides` to fake the LLM" — but the LLM was not a
dependency. Nodes imported and called Groq and Gemini directly. An audit
(grep for module-level settings, `SessionLocal(`, `from_url(`, `Depends(`)
found five hard-wired points, not the one flagged in the Day 4 handoff:
Groq, Gemini, the background task's own session, import-time settings in
`session.py` and `main.py`, and a Redis client shared with dev.

**2. `monkeypatch` would have been silently wrong**
`nodes.py` did `from app.services.llm import classify_ticket`, which copies
the reference at import. Patching `app.services.llm.classify_ticket` would
not reach the node. Chose injection over monkeypatch for this reason.

**3. The false pass, demonstrated on purpose**
Removed the LLM override. Real client hit Groq with the dummy key → 401 →
`classify_ticket` returned OTHER (never raises) → escalated → 201. The
`status == "escalated"` assertion passed. `len(fake_llm.classify_calls) == 1`
caught it. With that assertion also removed, the test passed while verifying
nothing.

**4. `InsecureKeyLengthWarning` from PyJWT**
The test JWT secret was 30 bytes; HS256 needs at least 32. Fixed the test key,
then checked the real one: 43 bytes, fine. Found only because warnings were
left visible instead of muted.

**5. pytest would have imported `scripts/`**
Default discovery collects any `test_*.py`. Six scripts matched; most make
real API calls at import and one did not parse. Fixed with `testpaths`.

**6. Placeholder left in a command**
Ran `GET /documents/PASTE_ID_HERE` → 404. Side observation: a malformed ID
returns the same 404 as a missing one, which is correct.

### Decisions

**Injection over monkeypatch**
Deciding factor: a wrong monkeypatch fails silently here, because
classification never raises; a missed injected dependency raises `TypeError`.
Also matches the plan and the existing `make_retrieve_node(db)` closure
pattern. Cost ~1.5–2 h. Monkeypatch is fine for code you can't change.

**`Protocol` over `ABC`**
Structural typing: fakes need not inherit from production code. Checked by
type checkers, not at runtime — a missing method is an `AttributeError` at
the call site, still loud.

**Clients are required keyword-only arguments with no default**
A default of `GeminiEmbedder()` would make a forgotten argument silently call
the real API in tests.

**Only the outermost layer chooses the provider**
Routes via `Depends`; scripts construct real providers directly (a script is
its own outermost layer). Services and nodes only pass through.

**Clients are closed over, not put in `TriageState`**
State is data about the ticket; it is streamed, asserted on, and could be
checkpointed. A client is a request-scoped tool and is not serialisable.

**Tests isolated by environment, not by refactoring `session.py`**
pytest loads `conftest.py` first, and env vars beat `.env` in
pydantic-settings. So test settings are in place before the first import
fixes them. The guard checks the *resolved* settings, not `os.environ` —
proves what the app will use, not what was intended. Refuses unless the
database ends in `_test` and Redis is not database 0. Tested by pointing it
at the dev database: refused.

**Real Postgres for tests, built by Alembic**
SQLite cannot run pgvector. `create_all` would skip `CREATE EXTENSION` and
the hand-written HNSW index. Alembic also tests the migrations.

**Truncate, not transaction rollback**
Services commit on their own, and `ingest_document` opens its own session,
so rollback cannot undo everything a test writes. Clean *before* each test
so a crashed test can't leave the next dirty. `FLUSHDB`, never `FLUSHALL` —
the latter would wipe dev's database 0.

**Fake embedder uses feature hashing**
Random vectors would never clear the 0.55 floor, making the drafted path
untestable. Bag-of-words hashing keeps "shared words → similar". `hashlib`,
not `hash()`, which Python randomises per process. Its behaviour against the
real `SIMILARITY_FLOOR` is itself tested.

**Fakes record calls**
Every ticket test asserts the fake was called. Without it, the false pass
above goes undetected.

**`clean_state` is not autouse**
Pure tests (fake embedder) should not need Postgres running.

**Admin created by SQL promotion in the fixture**
Mirrors the real process; there is no admin endpoint. Asserts
`rowcount == 1` because an UPDATE matching nothing does not error.

### Numbers

| Metric | Value |
|---|---|
| `POST /tickets` after refactor (real providers) | 2.11 s (Day 4 cold: 2.04 s) — within provider variance |
| Regression, `test_graph.py` | identical to Day 4: 0.6572 / 0.5874 / 0.5672, same categories and escalations |
| Regression, `test_retrieval.py` | identical to Day 3: top-1 5/5, all three score bands match |
| Unanswerable "university student discount" | top score **0.6495**, escalated on refusal sentence (DB-confirmed) |
| Test suite | 20 tests, ~5.1 s |
| bcrypt per hash (WSL venv, hash only) | ~0.22 s (Day 2's 0.36 s was a full login via curl — different measurement) |
| Share of suite time in fixture setup | 4 of 5 slowest entries are `setup`, ~0.48 s each (2 hashes) |
| Real JWT secret | 43 bytes (min 32) |

**Also observed:** the refund draft dropped "Renewal charges are not
refundable" in one run and included it in another within the hour — same
model, prompt and chunks. Live evidence for why tests fake the LLM.

### Open items

- **Remaining Day 5:** agent endpoint `GET /tickets/{id}` behind JWT; Upstash
  `rediss://` check; deploy (Neon, Upstash, Render); frontend; README
- Two Day 4 test tickets missed caches that never expire. **Suspected** Redis
  has no persistence volume — unverified. Matters for Day 11 hit rate.
- Draft cache key still uses `settings.groq_model`: the node knows a Groq
  setting name. Cleaner: model name on the provider.
- Test DB default URL in `conftest.py` repeats the dev password already in
  `docker-compose.yml`. Day 12.
- JWT key length is not enforced by `Settings`; only checked by hand. Day 12.
- CI (Day 14) will need `TEST_DATABASE_URL`, `CREATE DATABASE`, and
  `alembic upgrade head` before pytest.
- Starlette `DeprecationWarning` (anyio alias) — third-party, left visible.
- If the suite grows: lower bcrypt cost in tests only.
- **Closed today:** imports inside `get_document`; `session.py` module-level
  settings (resolved by import order + guard, not refactor); Day 3's
  "`POST /tickets` has not been called yet".

  ## Day 5 (part 2) — Agent endpoint, deployment, frontend, README

**Date:** 24–25 Sep 2026

### Built

- `GET /tickets/{id}` — agent-facing, JWT required. `TicketRead` extended
  with `subject`, `body`, `customer_email`, `created_at`.
  `get_ticket_with_citations` loads a ticket and its citations in two queries.
- Upstash Redis (Singapore, TLS, eviction on)
- `Dockerfile` hardened: listens on `$PORT`, `exec` so uvicorn is PID 1,
  runs as unprivileged `appuser`
- Neon production schema built with `alembic upgrade head` from WSL
- Render web service: Docker, Singapore, free tier, health check `/health`,
  auto-deploy on commit — https://ai-support-triage-4qzy.onrender.com/
- `scripts/seed_production.py` — idempotent: demo agent, admin (SQL
  promotion, verified via the deployed `/auth/me`), sample documents with
  polling until `ready`
- Production seeded: demo agent, admin, 3 documents ingested with Gemini
  called from Render
- Frontend `app/static/index.html`, served by FastAPI at `/`: customer panel
  streams triage progress; agent panel logs in and shows draft, confidence,
  sources and an escalation banner
- `.env.example` rewritten; `README.md` written
- Tests: 23 → 28 (agent endpoint ×3, frontend ×3, config ×2)
- Commits: `a089b3f` agent endpoint · `fe894f5` Dockerfile · `3abd110` seed
  script · `79a11f0` frontend · `949c404` `.env.example` · README

### What broke

**1. The Upstash URL was pasted as a `.env` line**
`REDIS_URL="rediss://..."` went into the variable, quotes included. redis-py
rejected the scheme. Printing only the part before the first `:`
(`${VAR%%:*}`) diagnosed it without revealing the secret. The clean-up
commands were then skipped once, so it failed again with the same error.

**2. Placeholders and a missing space**
`PASTE_ID_HERE` sent twice (422 in production). A missing space before `-H`
made curl read the header as a second URL, so the request went out with no
`Authorization` header (401). Fix: put values in variables, never splice
them into commands.

**3. The demo password shipped wrong, because a check was skipped**
`123456789` was typed at a hidden `getpass` prompt, twice. The login check
built to catch this was reported as "done" without output, so the wrong
password reached production and was only found in the browser. Fixed by
re-registering with the password visible in the command, then verified:
`triage-demo-2026 -> 200`, `123456789 -> 401`.

**4. The app hung instead of failing**
`main.py` mounted `app/static` before the folder existed. `StaticFiles`
checks at startup, so the app crashed; under `--reload` the reloader kept
port 8000 open, so requests hung rather than being refused. `--reload` only
watches `.py` files, so creating the folder didn't recover it. Fixed with a
restart. Now every `curl` in a check uses `--max-time`.

**5. 23 tests instead of 26**
The new test file wasn't saved yet. Same class as Day 1's unsaved buffer.

**6. `.env.example` had drifted**
`GROK_API_KEY` (a typo for `GROQ`), `JWT_SECRET_KEY` and `GEMINI_API_KEY`
missing, and an `ENVIRONMENT` line with no `=`. Anyone following it would hit
`Field required`. `pydantic-settings` ignores unknown variables silently,
which is how the typo went unnoticed. Now tested.

**7. Security finding after deploy: open registration grants staff access**
`POST /auth/register` is public and creates agents; agents read every
ticket. Harmless on a laptop, real once deployed. Demonstrated by using it
to re-create the demo account. Deferred to Day 12, stated in the README.

**8. A Day 0 claim was wrong**
Neon's free compute does scale to zero. Found by checking current docs
before deploying. Corrected in the Day 0 entry.

### Decisions

**Agent endpoint behind JWT, with a published demo login**
Instead of a public demo endpoint, which would have undone Day 4's rule
that drafts and scores stay private. Weakness: anyone with the demo login
reads every ticket. Mitigated by a fake prefilled email and a notice on
the page.

**No per-ticket ownership check**
Every account is staff, and staff read the whole queue. The docstring
records that customer accounts would require one (IDOR, OWASP API #1:
broken object level authorization).

**Citations via one explicit join, selecting four columns**
Walking relationships lazily is N+1 (8 queries for 3 citations). Eager
loading fixes the count but pulls `Document.raw_text`, the whole file,
just for a title. Verified with `engine.echo`: two queries.

**`uuid.UUID` path parameter**
A malformed ID gets 422 from FastAPI. `get_document` returns 404 for the
same input. The two are now inconsistent; recorded, not fixed.

**Everything in Singapore**
Measured from Delhi: every Upstash command costs ~93 ms. Same-region
calls from Render are around 1 ms.

**Neon direct connection, `postgresql+psycopg://`**
Not the pooler: one long-running process with its own SQLAlchemy pool,
and migrations need a direct connection. The prefix matters: plain
`postgresql://` means psycopg2, which isn't installed.

**Separate production JWT secret**
A leaked dev secret must not be able to sign production tokens.

**Health check `/health` on Render**
Gates each deploy: a version that can't reach Neon or Upstash never
replaces a working one. Cost: a query on Neon and a new Upstash TLS
connection on every probe. Frequency not yet measured.

**Container: `$PORT`, `exec`, non-root**
The platform picks the port. `exec` makes uvicorn PID 1 so SIGTERM reaches
it and it shuts down gracefully. Root would give an attacker full control
of the container.

**Seed script talks HTTP only and imports nothing from `app`**
So local `.env` settings can never leak into a production operation.
Idempotent (409 counts as done). Verifies through the deployed
`/auth/me` that the promotion reached the same database the app uses.

**Frontend served from the same origin**
No CORS configuration. Setting CORS to `*` to silence errors is the
classic mistake of the alternative.

**Streaming read with `fetch`, not `EventSource`**
`EventSource` can only GET. The reader buffers bytes and parses only
complete events, because network chunks don't line up with events.

**`textContent` only; token in memory in a module script**
The agent view shows text from strangers and from an LLM they can
influence. Verified by submitting `<img src=x onerror=...>`: displayed
literally. Enforced by a test that fails if `innerHTML` appears. In-memory
token reduces, not prevents, XSS damage; an HttpOnly cookie is the
production answer.

**Confidence labelled "top source similarity, not a probability"**
0.66 does not mean 66% likely correct.

**Reply-to-customer deferred**
Showing agent replies to customers needs a customer access design. Using
the ticket ID as the key turns it into a secret, and staff tools expose it.
The proper design is a per-ticket customer token. Recorded as "what I'd do
next."

**`.env.example` checked by a test**
Every required setting present, and no unknown names.

### Numbers

| Metric | Value |
|---|---|
| Agent endpoint queries | 2, whatever the citation count (verified) |
| Upstash from Delhi | 815 ms first PING (connect + TLS), 93 ms reused |
| Neon from Delhi, warm | 1559 ms connect + first query (not a cold start: migrations had just woken it) |
| `docker stop` with `exec` | 0.885 s (the no-`exec` case was not measured) |
| Production `/health` from Delhi | 0.81 s, then 0.27 s (the gap is probably DNS; not measured) |
| **Production cold ticket, streamed** | **2.09 s**, drafted (local cold: 2.04–2.11 s) |
| Production in browser | 1.25 s, partly cached; not a cold number |
| Local browser, cold / partly cached | 2.43 s / 1.05 s |
| Test suite | 28 tests, ~6.5 s |
| Production Postgres / pgvector | 18.6 / 0.8.6 (local: 16) |
| Render | port 10000, `WEB_CONCURRENCY=1` |

### Open items

- **Day 12:** close registration by default, add admin-created accounts,
  rate limiting
- **Measure:** time between Render health-check calls (log timestamps);
  Neon and Upstash usage dashboards
- `/health` opens a new Redis connection per call
- **Day 7:** Compose to `pgvector/pgvector:pg18` to match production (needs
  a volume reset)
- Migrations are manual on Neon: run them *before* pushing code that needs them
- Dockerfile reinstalls all dependencies on any code change
- Separate production Groq and Gemini keys, if dev keys were reused
- Ticket tests read the database directly (`stored()`); move them to the
  agent endpoint
- `get_document` (404) vs `get_ticket` (422) on malformed IDs
- **Unverified:** README Mermaid diagrams render on GitHub
- 90-second walkthrough done out loud, not reviewed
- Carried: suspected Redis has no persistence volume; draft cache key uses
  `settings.groq_model`
- **Closed:** agent endpoint; Upstash TLS; demo password; `.env.example`