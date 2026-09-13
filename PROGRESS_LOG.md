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