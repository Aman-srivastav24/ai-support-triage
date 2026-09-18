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
Render's free Postgres expires after 30 days. Neon's free tier is permanent and does not
pause on inactivity, which matters when a reviewer opens the link weeks after applying.

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