# AI Support Triage API

A FastAPI backend that triages customer support tickets. Each ticket is
classified, matched against the support documentation with vector search,
given a draft reply grounded in that documentation with citations, and either
returned to a support agent as a suggestion or escalated to a human.

**Nothing is ever sent to a customer.** It is a triage and drafting system with
a human in the loop.

> **Live demo:** https://ai-support-triage-4qzy.onrender.com/
> Demo agent login (prefilled on the page): `demo-agent@example.com` / `triage-demo-2026`
>
> Free hosting: the first request after 15 idle minutes takes about a minute
> while the service wakes. Please don't enter real personal data. The demo
> login is public, so anyone can read submitted tickets.

_Status: a 14-day learning build, currently at day 5. The roadmap is at the end._

---

## Architecture

```mermaid
flowchart LR
    C[Customer browser] -->|POST /tickets/stream, public| API
    A[Support agent] -->|JWT, GET /tickets/:id| API
    AD[Admin] -->|JWT, POST /documents| API
    subgraph Render
        API[FastAPI app]
    end
    API --> PG[(Neon Postgres + pgvector)]
    API --> R[(Upstash Redis cache)]
    API --> GQ[Groq: classify and draft]
    API --> GM[Gemini: embeddings]
```

### Ticket triage graph (LangGraph)

```mermaid
flowchart LR
    S((start)) --> classify --> retrieve --> draft --> score[score_confidence]
    score -->|any rule fires| esc[escalate]
    score -->|otherwise| ret[return_draft]
```

A ticket is **escalated** if any of these is true:

1. no retrieved chunk clears the similarity floor (0.55);
2. the draft contains the grounded refusal sentence ("The documentation does not cover this.");
3. the ticket is classified as `other`.

The rules are deterministic and cost no extra model call. The model is never
asked to rate its own confidence: self-reported confidence is least reliable
exactly when the model is fluently wrong.

More detail, including the data model and request sequence diagrams, is in
[docs/architecture.md](docs/architecture.md).

---

## Measured numbers

| What | Result | Notes |
|---|---|---|
| Ticket end to end, no cache | 2.04 s local · 2.09 s production | Production measured from Delhi against Render in Singapore |
| Ticket, every cache warm | 0.062 s | Best case only: requires identical ticket text |
| Share of cold latency spent in external APIs | ~95% | pgvector search itself: 5–18 ms |
| Top-1 retrieval | 5 / 5 | Only 5 hand-written questions. A 20-ticket eval set is next. |
| Similarity, answerable vs unanswerable questions | 0.587–0.656 vs 0.586–0.605 | The ranges overlap, so no threshold can separate them (see below) |
| Test suite | 28 tests, ~6.5 s | Real Postgres and Redis; only the AI providers are faked |

### The finding that shaped the design

Similarity measures whether a question is on topic, not whether the answer is
in the documents. "Is there a discount for university students?" scored
**0.6495**, near the top of the answerable range, although no such discount
exists. With a naive prompt, the model invented a plausible process for
applying for one. With a grounded prompt it replied "The documentation does not
cover this.", and the escalation rule caught that sentence. So escalation relies
on the grounded refusal, not on a similarity threshold.

---

## Design decisions

| Decision | Instead of | Why |
|---|---|---|
| pgvector in Postgres | Pinecone, Weaviate | One database for rows and vectors; transactional ingestion; HNSW index |
| HNSW index | IVFFlat | Builds on an empty table; IVFFlat needs representative data first |
| Gemini embeddings (768-d), Groq generation | One provider | Groq has no embeddings endpoint; 768-d fits pgvector's 2000-dimension index limit |
| LangGraph | One long prompt | Named steps, conditional routing, per-step streaming |
| Rule-based escalation | Model self-rated confidence | Deterministic, free, and not fooled by fluent wrong answers |
| FastAPI `BackgroundTasks` for ingestion | Celery | Small scale; the API already has a queue-shaped contract (202 plus status polling) |
| LLM and embedder injected as dependencies | `monkeypatch` in tests | A missed injection fails loudly; a wrong patch fails silently |
| Public receipt is `{id, status}` only | Returning the draft | Drafts and similarity scores would let anyone map the documentation |
| Frontend served by FastAPI | A separate frontend host | Same origin, so no CORS configuration |

---

## API

| Method | Path | Auth | Returns |
|---|---|---|---|
| GET | `/health` | none | Database and Redis status; 503 when degraded |
| POST | `/auth/register` | none | 201, new agent account |
| POST | `/auth/login` | none | JWT (form fields `username`, `password`) |
| GET | `/auth/me` | any user | The current user |
| POST | `/documents` | admin | 202; ingestion runs in the background |
| GET | `/documents/{id}` | admin | Ingestion status |
| POST | `/tickets` | none | 201, `{id, status}` only |
| POST | `/tickets/stream` | none | Server-Sent Events, one per triage step |
| GET | `/tickets/{id}` | any user | Full triage result: draft, confidence, citations |

Interactive docs: `/docs`.

---

## Run it locally

Requires Docker (with Compose) and Python 3.14.

```bash
cp .env.example .env          # then fill in JWT_SECRET_KEY, GEMINI_API_KEY, GROQ_API_KEY
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

docker compose up -d --build  # app on :8000, Postgres on :5433, Redis on :6379
alembic upgrade head          # build the schema

# Create a demo agent and an admin, and upload the sample documents
BASE_URL=http://127.0.0.1:8000 \
DATABASE_URL=postgresql+psycopg://triage:triage@localhost:5433/triage \
    python scripts/seed_production.py
```

Then open http://127.0.0.1:8000/.

## Run the tests

The tests use a separate `triage_test` database and Redis database 15, and
refuse to run against anything else.

```bash
docker compose exec db psql -U triage -d triage -c "CREATE DATABASE triage_test;"
DATABASE_URL=postgresql+psycopg://triage:triage@localhost:5433/triage_test alembic upgrade head
python -m pytest -q
```

## Deployment

App on Render (Docker, free tier), Postgres on Neon, Redis on Upstash, all in
Singapore. Migrations are run by hand against Neon before deploying code that
needs them, because the free tier has no pre-deploy step.

---

## Known limitations

- **Open registration grants agent access.** Anyone can create an account and
  read every ticket. Planned fix: registration closed by default, plus
  admin-created accounts.
- **No rate limiting yet** on the public ticket and registration endpoints.
- **Cold starts on the free tier:** about a minute for Render, plus a Neon wake-up.
- **`/health` is a deep check:** it queries Postgres and opens a new Redis
  connection on every call, and the platform calls it frequently.
- **Postgres 16 locally, 18 in production.**
- **Migrations are manual** in production.
- **A tiny corpus:** 3 documents of 1 chunk each, so chunk overlap is not
  exercised yet.
- **Confidence is the top similarity score, not a probability,** and it is not
  calibrated.
- **Classification is single-label.** Some tickets are both billing and technical.
- **The response cache matches exact text only.** Rephrased questions miss,
  and the hit rate has not been measured yet.

## Roadmap

In progress, following the 14-day plan: a retrieval evaluation set, hybrid
search with re-ranking, tool calling against customer data, a reflection step
that checks each claim against its sources, tracing and cost per ticket,
prompt-injection defences and rate limiting, an MCP server, and CI.

Beyond the plan:

- **Agent approve / edit / send**, with the reply delivered to the customer
  through a per-ticket access token (not the ticket ID, which staff tools
  expose). Agent edits double as evaluation data: each one marks where the
  model was wrong.
- **An HttpOnly session cookie** instead of a JavaScript-held token.