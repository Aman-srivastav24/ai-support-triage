# Architecture — AI Support Triage API

**Status:** Day 1 design. Updated as the build progresses.
**Last updated:** 13 Sep 2026

---

## 1. What this system is and is not

A FastAPI backend that ingests support documentation and, for each incoming
customer ticket: classifies it, retrieves relevant passages by vector search,
drafts a grounded reply with citations, scores its own confidence, and escalates
to a human when confidence is low.

**Boundary:** the system never contacts a customer. Every output is a draft that
a human support agent reviews. This is a triage-and-draft tool with a human in
the loop, and most of the failure-mode decisions below depend on that boundary.

---

## 2. System architecture

```mermaid
flowchart LR
    Customer -- "POST /tickets (public, rate-limited)" --> API
    Agent -- "JWT: review drafts" --> API
    Admin -- "JWT: upload docs" --> API

    subgraph app ["FastAPI application"]
        API["API layer\napp/api"] --> SVC["Services\napp/services"]
        SVC --> GRAPH["LangGraph agent\nclassify → retrieve → draft → check"]
        SVC --> BG["Background tasks\n(in-process, not durable)"]
    end

    SVC --> PG[("Postgres 16 + pgvector\nsource of truth")]
    BG --> PG
    GRAPH --> PG
    GRAPH --> REDIS[("Redis 7\ncache only")]
    GRAPH --> LLM["Groq\nchat completions"]
    GRAPH --> EMB["Embedding provider\n(decided Day 3)"]
```

| Component | Role | Failure impact |
|---|---|---|
| FastAPI | HTTP layer, validation, auth, dependency injection | Total outage |
| Postgres + pgvector | Users, documents, chunks, tickets, citations, embeddings | Total outage — let it 500 |
| Redis | Cache for query embeddings and responses | Slower, not down |
| Groq | Classification, drafting, confidence scoring | Tickets escalate to humans |
| Background tasks | Document ingestion, ticket processing | Stale `processing` rows; reprocess endpoint |

**Layering:** `api` (HTTP in/out, no business logic) → `services` (business
logic, no HTTP awareness) → `db` / `models` (persistence). The LLM provider is
called only from services, behind an interface, so tests can replace it with a
fake via `app.dependency_overrides`.

---

## 3. Roles

Three kinds of people. Two of them have accounts.

| Role | Has account | Can do |
|---|---|---|
| Customer | No | Submit a ticket, get a ticket ID |
| Agent | Yes (`role='agent'`) | List tickets, read drafts and citations, resolve tickets |
| Admin | Yes (`role='admin'`) | Everything an agent can, plus upload documents |

**Authentication** (who are you) is one endpoint, `POST /auth/login`, identical
for agents and admins. **Authorisation** (may you do this) is checked per
endpoint against `role`.

The word "agent" also refers to the LangGraph pipeline. That is code, not a
user, and has no row in any table.

Why customers don't log in: support forms are public everywhere; forcing signup
to report a problem is bad product. This makes `POST /tickets` an unauthenticated
internet-facing endpoint accepting free text — which is exactly why it gets rate
limiting and prompt-injection defence (Day 12).

Why upload is admin-only: documents become the retrieval corpus. Whoever can
upload can change what the AI says to every future customer.

---

## 4. Data model

### 4.1 Entity relationships

```mermaid
erDiagram
    users ||--o{ documents : uploads
    users |o--o{ tickets : "assigned to"
    documents ||--o{ chunks : "split into"
    tickets ||--o{ ticket_citations : "retrieved"
    chunks ||--o{ ticket_citations : "cited in"

    users {
        uuid id PK
        varchar email UK
        varchar hashed_password
        varchar role "agent | admin"
        boolean is_active
        timestamptz created_at
        timestamptz updated_at
    }

    documents {
        uuid id PK
        varchar title
        varchar source_filename
        char content_sha256 UK
        text raw_text
        varchar status "pending | processing | ready | failed"
        text error_message
        integer chunk_count
        uuid uploaded_by_id FK
        timestamptz created_at
        timestamptz updated_at
    }

    chunks {
        uuid id PK
        uuid document_id FK
        integer chunk_index
        text content
        integer token_count
        vector embedding "added Day 3"
        timestamptz created_at
    }

    tickets {
        uuid id PK
        varchar customer_email
        varchar subject
        text body
        varchar status "received | processing | drafted | escalated | failed | resolved"
        varchar category
        text draft_reply
        real confidence
        text escalation_reason
        uuid assigned_agent_id FK
        timestamptz created_at
        timestamptz updated_at
        timestamptz processed_at
    }

    ticket_citations {
        uuid ticket_id PK,FK
        uuid chunk_id PK,FK
        integer rank
        real score
        boolean used_in_reply
    }
```

### 4.2 Tables

**`users`** — support staff only. Customers are never in this table.

| column | type | constraints / notes |
|---|---|---|
| `id` | `UUID` | PK, default `gen_random_uuid()` |
| `email` | `VARCHAR(320)` | unique, not null, lowercased (320 = RFC 5321 max) |
| `hashed_password` | `VARCHAR(255)` | bcrypt output |
| `role` | `VARCHAR(20)` | not null, default `agent`, CHECK in (`agent`, `admin`) |
| `is_active` | `BOOLEAN` | not null, default true. Deactivate, never delete — tickets and documents reference users |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | not null, server default `now()` |

**`documents`** — one uploaded support document. The row exists before ingestion finishes.

| column | type | constraints / notes |
|---|---|---|
| `id` | `UUID` | PK |
| `title` | `VARCHAR(255)` | not null |
| `source_filename` | `VARCHAR(255)` | |
| `content_sha256` | `CHAR(64)` | unique — hash of extracted text, not file bytes |
| `raw_text` | `TEXT` | not null. Kept so Day 7 can re-chunk without re-upload |
| `status` | `VARCHAR(20)` | `pending` → `processing` → `ready` / `failed` |
| `error_message` | `TEXT` | nullable, set on `failed` |
| `chunk_count` | `INTEGER` | not null, default 0 |
| `uploaded_by_id` | `UUID` | FK → `users.id`, not null, `ON DELETE RESTRICT` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | |

**`chunks`** — ~500-token slice of a document, 50-token overlap.

| column | type | constraints / notes |
|---|---|---|
| `id` | `UUID` | PK |
| `document_id` | `UUID` | FK → `documents.id`, not null, `ON DELETE CASCADE` |
| `chunk_index` | `INTEGER` | not null, 0-based. `UNIQUE (document_id, chunk_index)` |
| `content` | `TEXT` | not null |
| `token_count` | `INTEGER` | not null |
| `embedding` | `vector(N)` | **Day 3.** Added with pgvector migration + index |
| `created_at` | `TIMESTAMPTZ` | |

**`tickets`** — a customer submission. Created on POST, before any AI runs; AI fields are nullable for that reason.

| column | type | constraints / notes |
|---|---|---|
| `id` | `UUID` | PK, doubles as the customer's reference |
| `customer_email` | `VARCHAR(320)` | not null |
| `subject` | `VARCHAR(500)` | nullable |
| `body` | `TEXT` | not null, length-limited at validation |
| `status` | `VARCHAR(20)` | `received` → `processing` → `drafted` / `escalated` / `failed` → `resolved` |
| `category` | `VARCHAR(50)` | nullable, set by classification (Day 4) |
| `draft_reply` | `TEXT` | nullable |
| `confidence` | `REAL` | nullable, 0.0–1.0 |
| `escalation_reason` | `TEXT` | nullable, free text (low similarity, LLM unavailable, …) |
| `assigned_agent_id` | `UUID` | FK → `users.id`, nullable, `ON DELETE SET NULL` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | |
| `processed_at` | `TIMESTAMPTZ` | nullable. `processed_at - created_at` = end-to-end latency |

There is deliberately no `sent_at`. The schema states the product boundary.

**`ticket_citations`** — which chunks were retrieved for which ticket, with scores. The audit trail and the input to Day 6 evals.

| column | type | constraints / notes |
|---|---|---|
| `ticket_id` | `UUID` | PK part, FK → `tickets.id`, `ON DELETE CASCADE` |
| `chunk_id` | `UUID` | PK part, FK → `chunks.id`, `ON DELETE CASCADE` |
| `rank` | `INTEGER` | 1 = best match |
| `score` | `REAL` | similarity at retrieval time |
| `used_in_reply` | `BOOLEAN` | default false |

### 4.3 `ON DELETE` rules

| FK | rule | reason |
|---|---|---|
| `chunks.document_id` | CASCADE | A chunk cannot exist without its document |
| `ticket_citations.*` | CASCADE | A citation cannot exist without both sides |
| `documents.uploaded_by_id` | RESTRICT | Documents outlive the person who uploaded them |
| `tickets.assigned_agent_id` | SET NULL | Tickets outlive the agent; they become unassigned |

Rule: CASCADE only when the child is meaningless without the parent.

---

## 5. Request flows

### 5.1 Flow A — admin uploads a document

```mermaid
sequenceDiagram
    actor Admin
    participant API as FastAPI
    participant DB as Postgres
    participant BG as Background task

    Admin->>API: POST /documents (JWT, file, title)
    API->>API: decode JWT (401) · check role=admin (403)
    API->>API: extract text · sha256
    API->>DB: SELECT id FROM documents WHERE content_sha256=?
    alt already exists
        API-->>Admin: 409 Conflict {existing id}
    else new
        API->>DB: INSERT documents (status='pending') · COMMIT
        API->>BG: schedule ingest(document_id)
        API-->>Admin: 202 Accepted {id, status: pending}
        BG->>DB: UPDATE status='processing'
        BG->>BG: chunk_text(size=500, overlap=50)
        BG->>DB: INSERT chunks (bulk) · UPDATE status='ready', chunk_count
        Note over BG,DB: on exception: UPDATE status='failed', error_message
    end
```

Key points:
- `202` not `201`: the document exists but is not yet usable.
- Commit happens **before** the task is scheduled; the task opens its **own** DB session.
- Admin polls `GET /documents/{id}` for `status`.

### 5.2 Flow B — customer submits a ticket

```mermaid
sequenceDiagram
    actor Customer
    participant API as FastAPI
    participant DB as Postgres
    participant G as LangGraph agent (background)
    participant R as Redis
    participant LLM as Groq

    Customer->>API: POST /tickets {email, subject, body}
    API->>API: Pydantic validation (422) · length limits
    API->>DB: INSERT tickets (status='received') · COMMIT
    API->>G: schedule process(ticket_id)
    API-->>Customer: 202 Accepted {id, status: received}

    G->>DB: UPDATE status='processing'
    G->>LLM: classify → structured output
    G->>R: GET embedding by hash(text)
    alt cache miss
        G->>G: embed(text) · SET in Redis
    end
    G->>DB: SELECT chunks ORDER BY embedding <=> query LIMIT 5
    G->>DB: INSERT ticket_citations (rank, score)
    alt top score below threshold
        G->>DB: UPDATE status='escalated', reason='no_relevant_context'
    else
        G->>LLM: draft from context (grounded prompt)
        G->>LLM: confidence (structured output)
        alt confident
            G->>DB: UPDATE draft_reply, confidence, status='drafted', processed_at
        else
            G->>DB: UPDATE draft_reply, confidence, status='escalated', reason
        end
    end
```

Key points:
- The ticket row is persisted **before** any AI runs. An LLM outage cannot lose a ticket.
- Citations are written **before** drafting. An LLM failure still leaves a record of what retrieval found.
- `processed_at - created_at` gives per-ticket latency without code changes.

### 5.3 Flow C — agent reviews a draft

```mermaid
sequenceDiagram
    actor Agent
    participant API as FastAPI
    participant DB as Postgres

    Agent->>API: POST /auth/login {email, password}
    API->>DB: SELECT users WHERE email=? AND is_active
    API->>API: bcrypt.checkpw · mint JWT {sub, role, exp}
    API-->>Agent: 200 {access_token}
    Note over API,Agent: any failure → 401, same message (no enumeration)

    Agent->>API: GET /tickets?status=drafted (Bearer)
    API->>DB: SELECT summary columns ... LIMIT 20
    API-->>Agent: 200 [summaries]

    Agent->>API: GET /tickets/{id} (Bearer)
    API->>DB: SELECT ticket + JOIN ticket_citations → chunks → documents
    API-->>Agent: 200 {ticket, draft, confidence, citations[]}

    Agent->>API: PATCH /tickets/{id} {status: resolved, final_reply}
    API->>DB: UPDATE tickets
    API-->>Agent: 200
```

### 5.4 Endpoint authorisation matrix

| endpoint | public | agent | admin |
|---|---|---|---|
| `GET /health` | ✓ | ✓ | ✓ |
| `POST /tickets` | ✓ | ✓ | ✓ |
| `POST /auth/register`, `POST /auth/login` | ✓ | ✓ | ✓ |
| `GET /tickets`, `GET /tickets/{id}`, `PATCH /tickets/{id}` | | ✓ | ✓ |
| `POST /documents`, `GET /documents/{id}`, `POST /documents/{id}/reprocess` | | | ✓ |

---

## 6. Data flow — from file to draft

```mermaid
flowchart TD
    F["Uploaded file"] --> T["Extracted text"]
    T --> H{"sha256 seen?"}
    H -- yes --> C409["409, return existing id"]
    H -- no --> D["documents row\nstatus=pending"]
    D --> CH["Chunk: 500 tokens, 50 overlap"]
    CH --> CR["chunks rows"]
    CR --> E["Embed each chunk (Day 3)"]
    E --> V["chunks.embedding\n+ ANN index"]

    TK["Ticket body"] --> QE["Embed query\n(Redis cached)"]
    QE --> S["Cosine similarity search\ntop-5 with scores"]
    V --> S
    S --> CIT["ticket_citations rows"]
    S --> TH{"top score ≥ threshold?"}
    TH -- no --> ESC["Escalate: no relevant context"]
    TH -- yes --> P["Prompt = instructions + delimited context + delimited ticket"]
    P --> LLM["LLM draft + confidence"]
    LLM --> CF{"confidence ≥ threshold?"}
    CF -- yes --> DR["tickets.status=drafted"]
    CF -- no --> ESC2["tickets.status=escalated"]
    DR --> HUM["Human agent reviews"]
    ESC --> HUM
    ESC2 --> HUM
```

`chunks` is the hinge. Ingestion exists to fill it; retrieval exists to search it.

---

## 7. Failure modes and decisions

| # | Failure | State left behind | Decision |
|---|---|---|---|
| 1 | Background task dies mid-run (restart, OOM) | Row stuck at `processing` | Accept; surface stale-row count in `/metrics`; admin `reprocess` endpoint. No Celery. |
| 2 | LLM down / rate-limited | — | Retry 2× with backoff (1s, 4s) on 429/5xx only. Then `escalated`, `escalation_reason='llm_unavailable'`. Ticket never lost. |
| 3 | Retrieval finds nothing relevant | Top-5 returned with low scores | Similarity threshold → escalate before calling LLM. Grounding prompt + confidence check as backup. Threshold tuned from Day 6 evals, not guessed. |
| 4 | Same document uploaded twice | Duplicate chunks would pollute top-k | `content_sha256` unique on extracted text → `409`. |
| 5 | Postgres unreachable | — | Let it 500. `pool_pre_ping=True` for Neon idle timeouts. `/health` reports DB separately. |
| 6 | Prompt injection via ticket body | Bad draft | Delimited, labelled untrusted input; length limits; **human review is the real control**. Full mitigation Day 12. |
| 7 | Redis down | — | Non-fatal. try/except around cache ops, log, continue. A cache is an optimisation, never a dependency. |

Three principles underneath these:
1. **Persist the input before doing anything that can fail.**
2. **Degrade to the human.** Every failure path ends with a person looking at it.
3. **Make stuck states visible** rather than building recovery that can't be maintained.

---

## 8. Design decisions and alternatives

| Decision | Alternative considered | Why this one |
|---|---|---|
| UUID primary keys | Auto-increment integers | Ticket IDs are public. Sequential IDs leak volume and allow enumeration. UUIDv7 if index fragmentation ever matters. |
| `VARCHAR` + CHECK for enums | Postgres native `ENUM` | `ALTER TYPE` is painful inside Alembic transactions; removing values is near-impossible. Statuses will change on Days 4 and 10. Type safety lives in Python `StrEnum` + Pydantic. |
| `TIMESTAMPTZ` everywhere | `TIMESTAMP` | Absolute instants, comparable across servers. UTC internally, convert at the edge. |
| Nullable AI columns on `tickets` | Separate `drafts` table | No need for multiple drafts per ticket or separate access control. Split later if Day 10 retry history needs it — additive migration. |
| `is_active` flag | Deleting users | Users are referenced by documents and tickets. History must survive staff turnover. |
| No soft deletes elsewhere | `deleted_at` columns | Every query needs the filter; the first forgotten one leaks data. |
| `raw_text` stored in Postgres | File on disk / object storage | Re-chunking on Day 7 needs the original. At scale this moves to S3 with a pointer. |
| pgvector | Pinecone / Weaviate / Chroma | One database, one transaction boundary, one backup. Vector search joined to relational data in a single query. Managed vector DBs earn their cost at millions of vectors, not thousands. |
| FastAPI `BackgroundTasks` | Celery / RQ | In-process, not durable, no retries — stated honestly. Swapping to a queue changes only what invokes the ingestion function. |
| JWT | Server-side sessions | Stateless; no session store to scale; matches what agents' tooling expects. Tradeoff: cannot revoke before expiry without a blocklist. |
| bcrypt | SHA-256 | Deliberately slow, salted, tunable work factor. Fast hashes are a brute-force gift. |
| Redis for cache only | Redis as queue/broker | Keeps the cache non-critical. Losing Redis slows things; it doesn't break them. |

---

## 9. Deferred (on purpose)

- `chunks.embedding` + pgvector extension + ANN index — Day 3
- Embedding provider (Groq has no embeddings endpoint) — Day 3
- Redis caching, streaming — Day 4
- Rate limiting, prompt-injection mitigation, PII redaction — Day 12
- Hybrid search, re-ranking — Day 8
- Reflection / retry loop — Day 10
- `/metrics`, tracing, cost per ticket — Day 11
- Durable task queue — out of scope; documented as the next step at scale

---

## 10. What this project does not claim

No Celery, no Kubernetes, no managed vector database, no fine-tuning, no
production scale. See the plan document for the full list.
