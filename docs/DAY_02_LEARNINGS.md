# Day 2 — What I Learned

**AI Support Triage API · 16 Sep 2026**

Today had two halves:

1. **Auth** — letting people register, log in, and proving who they are on every request afterwards.
2. **Ingestion** — letting an admin upload a support document, cutting it into small pieces, and doing that cutting *after* the response is sent.

This document explains what we built, why we built it that way, and what broke.

---

# Part 1 — Why authentication is hard at all

## The internet has no memory

Here is the thing that makes all of this necessary:

**Every HTTP request arrives as a total stranger.**

You log in. One second later you click something else. The server has no idea you're the same person. It doesn't remember the login. It doesn't remember you at all.

So after login, **something has to travel with every single request to prove who you are.**

## The cinema ticket

You buy a ticket at the counter. That's login — you show your ID (email + password) once.

Now you walk to the screen. The person at the door doesn't remember your face. But he doesn't need to — you hand him the ticket. He checks it's real and lets you in.

A **JWT** (JSON Web Token) is that ticket.

- You log in once with email and password → the server hands you a token.
- Every request after that, you send the token in a header.
- The server checks the token is real and works out who you are from it.

## Two ways to do tickets

**Way 1 — the guest list (called "sessions").**

The server keeps a notebook: *"ticket #8821 = Aman, agent."* You show ticket #8821, the server looks it up.

- Good: you can cross someone out instantly.
- Bad: the server has to keep and search that notebook for every request. If you run five servers, they all need the same notebook, so you end up storing it in something shared like Redis.

**Way 2 — the printed ticket (JWT).** ← what we built

Everything is written on the ticket itself: *"user 4feb689f, role agent, valid until 3pm."* No notebook.

- Good: any server can check it instantly, no lookup, no shared storage.
- Bad: you can't un-print a ticket that's already in someone's pocket.

## But if it's all printed on the ticket, can't I print my own?

This is the right question, and it's the whole trick.

The server puts a **stamp** on the ticket. The stamp is calculated from **the words on the ticket** combined with **a secret only the server knows** (our `JWT_SECRET_KEY`).

Change one letter — `agent` → `admin` — and the words no longer match the stamp. The server recalculates, sees the mismatch, rejects it.

**You can read a JWT. You cannot change one without the secret.**

## What a token actually looks like

Three chunks of gibberish joined by dots:

```
eyJhbGciOiJIUzI1NiJ9 . eyJzdWIiOiI0ZmViNjg5ZiIsInJvbGUiOiJhZ2VudCJ9 . 4Xp2kQ...
      header                          payload                          signature
```

| Part | What it is |
|---|---|
| **Header** | "this ticket was stamped using method HS256" |
| **Payload** | the actual facts: who you are, your role, when it expires |
| **Signature** | the stamp — proof it's genuine |

The facts inside the payload are called **claims**. Just a fancy word for "things the ticket claims about you."

Standard ones we use:

- `sub` — **subject**, meaning *who this is*. We put the user's ID here.
- `exp` — **expiry**, when it stops working
- `iat` — **issued at**, when it was created
- `role` — our own custom one: `agent` or `admin`

You saw this yourself today. When you ran the login command, the token started with `eyJhbGciOiJIUzI1NiIs` — that's base64 for `{"alg":"HS256"...`. The header, readable right there in your terminal.

## ⚠️ The thing almost everyone gets wrong

**A JWT is not encrypted. It is signed.**

Those are different:

- **Encrypted** = nobody can read it.
- **Signed** = anyone can read it, nobody can change it.

Anyone holding your token can read every claim inside. It's a printed cinema ticket — readable by all, forgeable by none.

**So never put anything private in a token.** No passwords. No personal details. Just an ID and a role.

> **Interview question:** *"Is a JWT encrypted?"*
> **Answer:** *"No — it's signed, not encrypted. The signature stops tampering, it doesn't stop reading. That's why nothing sensitive goes in the payload."*

## The real weakness of JWTs

**You cannot cancel a token you've already issued.**

Back to the cinema: once the ticket is printed and in your hand, the manager can't reach into your pocket and tear it up.

If an agent is fired at 2pm and their token is valid until 3pm — **it still works until 3pm.**

How people deal with this:

- **Short expiry.** We use 60 minutes. Worst case, a stolen token is dangerous for an hour.
- **A banned-tokens list.** But now the server is keeping a notebook again — the exact thing JWTs were avoiding.

There is no perfect answer. **Knowing the tradeoff is the answer.**

## Our mitigation: check the database every request

Here is a decision we made that's worth understanding properly.

Our `get_current_user` function could just read the role off the token — it's right there, it's trustworthy (the signature proved that), and it would save a database query.

**We don't do that.** Instead:

```
token arrives
  ↓
verify the stamp
  ↓
read the user ID from the token
  ↓
GO AND FETCH THAT USER FROM THE DATABASE   ← the extra step
  ↓
check they're still active
  ↓
check their role (from the database, not the token)
```

**Why pay for that lookup?** Because it makes changes take effect *immediately*:

- Set `is_active = false` → they're locked out on their very next request.
- Change someone's role → it applies instantly.

**You proved this today without realising it.** You promoted your user to admin with SQL. Their token still said `role: agent`. Uploading worked anyway — because the role we check comes from the database, not the token.

**Cost:** one indexed primary-key lookup, about a millisecond.
**Benefit:** instant revocation instead of waiting up to an hour.

> **The rule:** the token answers *"who are you?"*. The database answers *"what are you allowed to do?"*
> The `role` claim in the token is only useful for a frontend deciding whether to show an admin menu. It must never be what authorisation decides on.

---

# Part 2 — Passwords

## Rule zero: never store a password

Not in the database. Not anywhere.

If your database leaks and passwords are in it, every user's password is public. And because people reuse passwords, you've just leaked their bank login too.

## So how do you check a password you don't have?

You store a **hash**.

A hash is a **one-way blender**. Put `mypassword123` in, get `a3f5b8c2...` out. There is no un-blend button. You cannot get back from the smoothie to the fruit.

Login works like this:

1. User types their password
2. You blend it
3. Compare the result to the blended version in your database
4. Same → correct. Different → wrong.

You checked the password without ever storing it.

## Why not just use SHA-256?

SHA-256 *is* a hash, and it's excellent at its job. But its job is being **fast** — it's built for checking that a 4GB download wasn't corrupted.

Fast is exactly wrong for passwords.

A gaming graphics card computes **billions** of SHA-256 hashes per second. So if your table leaks:

1. Attacker grabs a list of the million most common passwords
2. Hashes all of them — takes seconds
3. Compares against your leaked table
4. Everyone with a common password is cracked

It gets worse: SHA-256 always gives the same output for the same input. So **every user who chose `password123` has an identical hash in your table.** Crack one, crack all of them. And attackers have pre-built lookup tables of common-password→hash pairs, so they don't even need to do the hashing.

## What bcrypt does differently

### Fix 1 — deliberately slow

bcrypt has a dial called the **cost factor**. We set it to **12**.

**You measured this today: 0.36 seconds per hash on your machine.**

- Real user logging in: 0.36s. They don't notice.
- Attacker trying a billion guesses: 0.36s **each**. Years instead of seconds.

And when computers get faster, you turn the dial to 13, then 14. The protection ages with the hardware.

### Fix 2 — the salt

Before hashing, bcrypt generates a random string called a **salt** and mixes it into the password. A different random salt for every user.

Result: two people both using `password123` get **completely different** hashes. Crack one, learn nothing about the other. Pre-built lookup tables become useless, because the attacker would need a separate table for every possible salt.

The salt isn't secret — it's stored inside the hash string itself:

```
$2b$12$KIXxPfnK6VcQ7oX1mB2wOe...
 │   │  └─ random salt, then the hash
 │   └──── cost factor = 12
 └──────── "this is bcrypt"
```

That's why our `User` model has no separate salt column. Everything needed to verify is in that one 60-character string.

## The mirror image: SHA-256 for the document fingerprint

Here's the part that ties it together nicely.

We used **SHA-256** for something else today — the document fingerprint (`content_sha256`). Same family of tool, **opposite requirements**.

| | Passwords (bcrypt) | Document fingerprint (SHA-256) |
|---|---|---|
| **Goal** | hide the original | detect an exact duplicate |
| **Speed** | slow on purpose | fast |
| **Same input twice** | different output (salt) | **identical** output |

For the fingerprint we *need* the same text to always produce the same result — otherwise we could never spot a duplicate upload. bcrypt's randomness is a **feature** for passwords and would be a **bug** here.

> **Interview line:** *"Hashing is one-way, encryption is two-way. If a website can email you your old password, they're storing passwords wrong."*

## The timing attack (this one is subtle and worth understanding)

**The attack:** an attacker wants to find out *which email addresses have accounts on your system*. That's step one of targeting people — now they know who to phish.

They don't need to guess passwords. They just need to spot a difference.

**Where the difference came from.** Without a fix, our login did this:

- Email doesn't exist → look it up, find nothing, return immediately → **~1 millisecond**
- Email exists, wrong password → look it up, run bcrypt → **~360 milliseconds**

A 360× difference. The attacker doesn't even need to read the error message. They just **time the response**. Fast = no account. Slow = account exists.

This is called a **timing attack**, and what it leaks is **user enumeration** — discovering which accounts exist.

**The fix.** When the email doesn't exist, we run bcrypt anyway against a fake hash that nothing matches. The result is thrown away. The only purpose is to burn the same quarter second.

**What you measured today:**

| Case | Time |
|---|---|
| Wrong password | 0.362s |
| Unknown email | 0.356s |

A 6ms gap on a 360ms operation. That's noise, not a signal. Nothing left to measure.

We also return the **same message** for all three failure types — no such user, wrong password, deactivated account. Same time, same message, nothing to learn.

### One honest gap we left

`POST /auth/register` returns **409 Conflict** when the email is taken. That *does* reveal an account exists.

The proper fix is what Gmail and GitHub do: always respond as if it succeeded, then email the real owner. That needs email infrastructure we don't have.

**Knowing your own gap is worth more than pretending it isn't there.** If asked, say exactly that.

---

# Part 3 — How the code is organised (layers)

We didn't put everything in one file. Here's why that matters.

```
app/
├── api/         ← the ONLY layer that knows HTTP exists
│   ├── deps.py       shared dependencies (auth checks)
│   ├── auth.py       /auth/register, /auth/login, /auth/me
│   └── documents.py  /documents
├── services/    ← the actual rules. No HTTP anywhere.
│   ├── auth.py       create_user, authenticate_user
│   ├── chunking.py   split text into pieces
│   └── documents.py  create_document, ingest_document
├── schemas/     ← what data is allowed in and out
├── models/      ← what the database tables look like
├── core/        ← config and security tools
└── db/          ← database connection
```

## The rule

**`services/` and `core/` know nothing about HTTP.** No status codes, no `HTTPException`, no requests.

They raise our own plain Python exceptions:

- `TokenError`
- `InvalidCredentials`
- `EmailAlreadyRegistered`
- `DuplicateDocument`
- `EmptyDocument`

**`api/` is the only layer that turns those into status codes.** `InvalidCredentials` → 401. `DuplicateDocument` → 409.

## Why bother?

**1. You can test without a web server.** Every single thing we built today, you tested by running a plain Python script. No browser, no FastAPI, no requests. Just `create_user(db, ...)` and `ingest_document(id)` called directly.

That's not an accident — it's what the separation buys you. On Day 5 when we write real tests, they'll be fast because of this.

**2. You can reuse the logic.** Need to create a user from a command-line script, or a seed file, or a background job? Just call `create_user`. If that logic lived inside an HTTP endpoint you'd have to fake a web request to reach it.

**3. Routers stay thin.** Look at `app/api/auth.py` — there is not one business rule in it. No hashing, no uniqueness checking. It calls a service, catches an exception, picks a status code. That's the entire job of a router.

> **If you find yourself writing business logic in a router, it belongs in a service.**

## Schemas: the allowlist

This one is a genuine safety mechanism, not just tidiness.

Your `User` model has a `hashed_password` column. Your `Document` model has `raw_text` — potentially megabytes.

If FastAPI serialised those objects directly, **every response would leak them.**

Instead we define a schema listing exactly which fields may leave:

```python
class UserRead(BaseModel):
    id, email, role, is_active, created_at    # hashed_password is NOT here
```

FastAPI filters the object through that before responding. The field exists on the object; it simply cannot appear in the response.

**This is an allowlist, not a blocklist.** You have to *opt in* to exposing a field. That matters because forgetting to hide something is a far easier mistake than forgetting to show something.

**You tested this today** and got `raw_text leaked: False`, `sha leaked: False`. Verifying rather than trusting.

### The same idea protects against privilege escalation

Look at our registration schema:

```python
class UserRegister(BaseModel):
    email: EmailStr
    password: str
```

**There is no `role` field.** That's deliberate, not an oversight.

If `role` were accepted as input, anyone could register as an admin by sending `{"email": "...", "password": "...", "role": "admin"}`. That's a real and common vulnerability called **privilege escalation**.

Registration always creates an agent. Admins are promoted by an existing admin. **You tested this** and got `role field ignored: True` — Pydantic silently dropped the extra key.

---

# Part 4 — Ingestion, and why upload must return instantly

## The problem

An admin uploads a support manual. Before it's useful we have to **chunk** it — cut it into small pieces. On Day 3 we'll also send every piece to an AI service. For a real manual that's 30+ seconds of work.

Now imagine the endpoint did all that before replying:

1. Admin's browser sits there spinning
2. After 30 seconds it gives up with an error
3. The browser retries automatically
4. **The same document gets ingested twice**

## The restaurant

You order food. The waiter doesn't stand frozen at your table until the chef finishes. He writes it down, says **"got it, order 47,"** and walks away. Cooking happens in the back.

That's what we built:

```
admin uploads
      ↓
save the document row, status = "pending"
      ↓
respond immediately: 202, here's your ID          ← request is OVER here
      ↓
────────────────────────────────────────────
      ↓
status = "processing"
      ↓
cut the text into chunks, save them
      ↓
status = "ready", chunk_count = 4
```

**You watched this happen today.** The upload returned `status: pending, chunk_count: 0`. Seconds later, `GET /documents/{id}` returned `status: ready, chunk_count: 4`. Same document, same endpoint — work happened in between.

## Why 202 and not 201

| Code | Means | Right here? |
|---|---|---|
| **201 Created** | the thing is made **and ready** | No — that would be a lie |
| **202 Accepted** | request taken, valid, work will happen, check back | Yes |

202 is honest. And the response carries a `status` field plus an ID, and `GET /documents/{id}` is where you check. That combination — **202 + status field + polling endpoint** — is the standard way to express slow work in an API.

> **Interview question:** *"How do you handle long-running work in an API?"*
> **Answer:** *"Return 202 immediately with a resource ID and a status field, do the work asynchronously, and let the client poll. That way a slow job never holds a connection open or times out the client."*

## FastAPI's `BackgroundTasks`

FastAPI has this built in: *"after you send the response, run this function."* No extra software.

**Its limits — know these, they're the whole interview answer:**

- If the process crashes or restarts mid-task, **the work is just gone.** Nobody retries it.
- Nothing tells you a task failed or got stuck.
- It runs inside the API process, so heavy chunking competes with serving requests.
- You can't add chunking capacity without adding API servers.

## The grown-up version: a task queue

Bigger systems use a **task queue** — Celery, RQ, arq, Dramatiq.

- The API doesn't do the work. It drops a note — *"chunk document 47"* — into a shared inbox (a **broker**, usually Redis).
- Separate programs called **workers** watch that inbox and do the work.

Better because: the note survives an API restart, failed jobs retry automatically, you can see what's queued, and you scale workers separately.

**Why we didn't:** one admin, a handful of uploads, 14-day project. Celery would be more plumbing than product.

## But we built it the queue way anyway

Even using the simple tool, we copied the grown-up design:

- `Document` has a **status** column: `pending → processing → ready | failed`
- Upload returns the ID immediately
- The client polls that ID

**Why this matters:** if we later swap in Celery, **only the engine changes.** The API behaves identically from the outside.

> **Interview question:** *"What would you do if this had to handle 10,000 uploads a day?"*
> **Answer:** *"Move the ingestion to a real task queue with dedicated workers. The API contract wouldn't change — it already returns 202 with a status the client polls, so only the executor is swapped."*

## And we mitigated the biggest weakness by hand

The background task runs **after the response is sent**, so there's no HTTP response left to fail into. An uncaught error would vanish into the logs and leave the document stuck at `processing` forever with no explanation.

So `ingest_document` catches **every** exception, sets `status = failed`, and stores the reason in `error_message` — which we deliberately expose in `DocumentRead`.

**A failure the user can see beats a failure only the logs know about.**

## ⚠️ The trap: background tasks take IDs, not objects

This is the single most common bug in this pattern, so understand it properly.

The database connection used during the request **closes when the response is sent**. The background task starts *after* that.

A `Document` object is tied to the connection that loaded it. Hand that object to the task and the first time it touches `document.raw_text`, the connection is dead and it crashes with a confusing error.

So:

```python
background_tasks.add_task(ingest_document, document.id)   # ✅ the ID
```

And `ingest_document` opens its **own** connection and loads the document itself.

**It also closes that connection in a `finally` block.** Skip that and every upload leaks a connection. After about ten uploads the pool is exhausted and the whole app hangs waiting for a free one — slow, confusing, and it only appears under load.

> **The rule:** background tasks get IDs, never database objects. And whoever opens a connection closes it.

---

# Part 5 — Chunking

## Why split documents at all

On Day 3 we turn text into **embeddings** — lists of numbers that capture meaning — so we can search by *meaning* rather than keywords. Three reasons a whole document can't be one embedding:

**1. One embedding is one meaning.** Squeeze a 40-page manual into one vector and you get the *average* of everything it discusses. Search for "reset my password" and it matches weakly against a document that's mostly about billing. Smaller pieces have sharper, more specific meaning.

**2. The context window.** Whatever we retrieve gets pasted into the prompt we send the AI, and prompts have a size limit. You can't paste 40 pages. You can paste five short passages.

**3. Precision.** If the answer is one paragraph, sending five pages means the model has to find it — and models get less reliable the more irrelevant text surrounds the answer.

## Why chunks overlap

Split at a fixed size and you will eventually cut an explanation in half:

```
chunk 4: "...to reset your password, open Settings and"
chunk 5: "click Security, then Reset. A link arrives by email."
```

Neither chunk answers the question fully.

**Overlap** means each chunk repeats the last ~50 tokens of the previous one, so every boundary appears intact somewhere. Costs a little duplicate storage; buys you not losing answers at the seams.

## How it works in code

```
chunk size = 500,  overlap = 50,  so step = 450

chunk 0:  tokens    0 – 500
chunk 1:  tokens  450 – 950      ← 450-500 repeated from chunk 0
chunk 2:  tokens  900 – 1400     ← 900-950 repeated from chunk 1
```

One line does it: `step = chunk_size - overlap`.

**You verified the overlap is really there** rather than assuming — the tail of chunk 0 appeared inside chunk 1.

## The tradeoff (this is the interview question)

| | Small chunks (~200) | Large chunks (~1000) |
|---|---|---|
| **Precision** | High — tight, specific meaning | Low — diluted |
| **Context** | Poor — may lack surrounding explanation | Good — self-contained |
| **Count** | Many — more storage, slower search | Fewer |

**There is no universally correct size.** 500/50 is a sane default.

**Day 7 is where we test three sizes against the eval set and measure which actually wins.** That measurement is the real answer to *"how did you pick your chunk size?"* — and **"I measured it"** beats **"it's the standard"** every time.

## Tokens, not characters

A **token** is roughly a word-piece — about ¾ of a word in English. AI models count tokens, not characters, and so do their price lists. We use `tiktoken` to count properly instead of guessing.

**Honest limitation:** `cl100k_base` is OpenAI's tokenizer, and we're calling Groq or Gemini. So our counts are *approximately* right, not exact. Fine for sizing chunks. Not fine for billing.

> **Interview-safe phrasing:** *"I used tiktoken's cl100k_base for chunk sizing. It's not the exact tokenizer for the model I call, so counts are approximate. For real cost tracking you'd use the token usage the provider returns in its response rather than a local estimate."*

## A second honest limitation

We split purely on token count, **ignoring paragraph and section boundaries.** Better implementations split on structure first — paragraphs, then sentences — and only fall back to hard cuts.

That's a real improvement and it's deliberately out of scope for 14 days.

> **If asked:** *"I used fixed-size token chunks with overlap. The next improvement is structure-aware splitting on paragraph boundaries."*

---

# Part 6 — Two layers of protection against duplicates

We used the same pattern twice today — unique emails, and unique document fingerprints. Understand it once and it applies to both.

## The race condition

Say we only checked in Python:

```python
if email_already_exists(email):
    raise Error
create_the_user(email)        # ← a gap exists between these two lines
```

Two registration requests for the same email arrive a millisecond apart:

1. Request A checks → not found
2. Request B checks → not found
3. Request A inserts
4. Request B inserts

**Two accounts, one email.** Login is now ambiguous.

The problem is that the check and the write are two separate operations, and anything can happen in between.

## The fix: let the database guarantee it

Both columns have `unique=True`, which creates a **unique index** in Postgres. The database **physically refuses** to store a second row with the same value — and its check and write happen as one atomic operation, so there's no gap.

So we do both:

```python
if already_exists(...):           # nice error message for the normal case
    raise DuplicateDocument
try:
    db.commit()
except IntegrityError:            # the database catching the millisecond race
    db.rollback()
    raise DuplicateDocument
```

> **The rule:** application validation is for **user experience**. Database constraints are for **correctness**. You need both, and they do different jobs.

## ⚠️ `db.rollback()` is not optional

After an `IntegrityError`, the transaction is in a **failed state** and Postgres rejects every further statement on that connection until you roll back.

Skip the rollback and the **next** request using that connection fails with a baffling *"current transaction is aborted"* error — and you'll be hunting in completely the wrong place.

This is a genuinely common production bug.

---

# Part 7 — Status codes we used and why

| Code | Name | When | Where today |
|---|---|---|---|
| **200** | OK | normal success | login, `/auth/me` |
| **201** | Created | a resource was made and is ready | register |
| **202** | Accepted | request taken, work happens later | document upload |
| **400** | Bad Request | malformed input | not valid UTF-8 |
| **401** | Unauthorized | **I don't know who you are** | no/bad/expired token |
| **403** | Forbidden | **I know you, you're not allowed** | agent uploading |
| **404** | Not Found | no such thing | bad document ID |
| **409** | Conflict | valid request, conflicts with current state | duplicate email or file |
| **413** | Too Large | over the size limit | file over 5MB |
| **415** | Unsupported Media Type | wrong file type | non-text upload |

## 401 vs 403 — learn this cold, it's a common interview question

**401 Unauthorized** — *"I don't know who you are."*
No token, broken token, expired token, forged token.
**Fix: log in.**

**403 Forbidden** — *"I know exactly who you are. You're still not allowed."*
Your token was perfect. You're `agent2@example.com`. Uploading needs admin.
**Fix: nothing you can do. Someone has to grant you permission.**

**The names are historically backwards.** 401 is *called* "Unauthorized" but actually means **unauthenticated**. 403 is the one about authorization. Everyone finds this annoying. Remember the meanings, not the names.

**Memory hook:**
- **401 = Who are you?**
- **403 = I know who you are. No.**

You produced both today: `agent2` uploading → **403**. Missing token → **401**.

## Why every auth failure returns the same message

Expired token, forged signature, valid token for a deleted user, valid token for a deactivated user — **all return the identical 401 with the identical message.**

That feels unhelpful. It's deliberate.

*"Token expired"* tells an attacker their forgery was structurally fine and only the clock beat them. *"User not found"* confirms the ID they guessed doesn't exist. Give them one flat wall.

Your logs can record the real reason — that's Day 11 — but the **response** says nothing.

## And never let bad input cause a 500

`uuid.UUID("garbage")` raises an error. Uncaught, that's a **500 Internal Server Error** — a crash triggered by user input.

We catch it and return **404** instead.

> **The rule:** a 500 means a bug in your code. A 401/404 means a bad request. Malformed input must never produce a 500 — an endpoint that crashes on weird input is an endpoint someone can crash on purpose.

Why 404 and not 400? Because a malformed ID and a well-formed ID that doesn't exist should look **identical** to the caller. Same reasoning as the flat 401.

---

# Part 8 — What broke today, and what each one taught

## 1. Container wouldn't start: `jwt_secret_key Field required`

**What happened:** `.env` had the key. The container didn't. The app refused to start.

**Why:** `.dockerignore` excludes `.env` — **correctly**, because secrets must never be baked into an image. So the container only sees what Docker Compose's `environment:` block passes it. Nobody told Compose about the new variable.

**Fix:**

```yaml
JWT_SECRET_KEY: ${JWT_SECRET_KEY:?JWT_SECRET_KEY is not set}
```

The `:?message` part means Compose **refuses to start** if the variable is missing, instead of quietly substituting an empty string.

> **Lesson:** every new setting goes in **two places** — `.env` for local runs, Compose `environment:` for the container. Miss one and it works in one place and fails in the other. This is the most common "works on my machine" bug in containerised apps.

**And notice the good part:** the app *refused to start* with a clear message naming the exact field, at startup, before any request. That's **fail-fast**, and it's why `jwt_secret_key` has no default value.

If it had defaulted to something like `"changeme"`, the app would have started happily with a secret identical in every copy of this project on earth — meaning anyone could forge admin tokens against your deployment. **A broken deploy is obvious. A deploy running on a public default secret is invisible until you're breached.**

## 2. `ModuleNotFoundError: No module named 'tiktoken'`

**What happened:** every local test worked. The container died.

**Why:** `tiktoken` was installed into your **venv** on Day 0 while testing Python 3.14 compatibility. It was never added to `pyproject.toml`. The image is built **only** from what's declared there.

> **Lesson:** your venv accumulates everything you've ever installed. The image only gets what's written down. **Anything not declared works locally and dies in the container.**

**Habit:** before every `docker compose up --build`, ask — *did I import anything this week that isn't in `pyproject.toml`?*

## 3. `http://localhost:8000` unreachable from the browser

**What happened:** the app was completely healthy — `curl` from inside WSL returned 200. But Windows said "can't be reached."

**Why:** Windows resolves `localhost` to the IPv6 address `::1` first. WSL2's port forwarding only listens on IPv4. So Windows knocked on a door that doesn't exist.

**Fix:** use `http://127.0.0.1:8000` — forces IPv4.

Same root cause family as the Day 0 `apt` IPv6 failure. **Two IPv6 bites in two days — that's a pattern, not a coincidence.**

## 4. `Could not validate credentials` on a curl request

**What happened:** `$TOKEN` was empty in that terminal — the upload had been done through `/docs`, which holds its own token.

**Not a bug.** And worth noticing what the message *didn't* say: not "token missing," not "token expired." One flat message. The design from Part 7 working exactly as intended.

## 5. A process lesson

Early on, I wrote out a full `User` model for you to paste — **without reading your existing one first.** Yours already had everything, plus mixins and relationships my version would have destroyed.

> **Lesson, and it applies to you at work too:** never rewrite a file you haven't read. On a real team, that's how you silently delete a colleague's work.

This is also why your `PROGRESS_LOG.md` now has a **"Files and what's in them"** section. Ten lines describing what exists means the next person — probably you in three weeks — starts from knowledge instead of guesswork.

---

# Numbers I measured today

Write these down. They're interview answers, and **"I measured it" always beats "I read that..."**

| Metric | Value |
|---|---|
| bcrypt cost factor | 12 |
| bcrypt hash time (this machine) | **0.36 s** |
| Login — wrong password | **0.362 s** |
| Login — unknown email | **0.356 s** (6 ms gap — enumeration defence holding) |
| JWT expiry | 60 min |
| Chunk size / overlap | 500 / 50 tokens (step 450) |
| Test: 2001 tokens | 5 chunks, last one 201 tokens |
| policy.txt ingestion | 4 chunks, pending → ready |
| Upload size cap | 5 MB |

---

# What I can honestly claim from Day 2

✅ JWT authentication — issuing, verifying, and the revocation tradeoff
✅ bcrypt password hashing and why fast hashes are wrong for passwords
✅ Role-based access control with a real reason to exist
✅ Timing-attack defence against user enumeration, measured
✅ FastAPI dependency injection and dependency chaining
✅ Layered architecture — services that are testable without a web server
✅ Pydantic schemas as an allowlist at the API boundary
✅ Async upload with 202 and a polling contract
✅ FastAPI `BackgroundTasks`, and when you'd graduate to a real queue
✅ Token-based text chunking with overlap
✅ Two-layer duplicate protection (application check + database constraint)

## ❌ What I must NOT claim

❌ **"I've used Celery."** I haven't. I used `BackgroundTasks` and can explain when and why you'd move to a queue. **That honest version is the stronger answer** — it shows I chose a tool deliberately instead of copying a tutorial.

❌ **"I built a production auth system."** It has known gaps I can name: register leaks account existence, no refresh tokens, no rate limiting yet, no password reset.

❌ **"I know async Python."** I used `async def` for one endpoint and I know my database driver is synchronous, which means it blocks the event loop. Knowing that is not the same as having built an async system.

---

# Questions I should be able to answer out loud, no notes

1. A JWT is readable by anyone who has it. **So what stops an agent editing theirs to say `role: admin`?** And why did promoting a user to admin work immediately even though their old token still said `agent`?

2. **Why bcrypt for passwords but SHA-256 for the document fingerprint?** Same job — hashing — opposite requirements. Name both.

3. **Walk the upload from `POST /documents` to `status: ready`.** Which status code, why that one, where the response ended, what ran afterwards, and why the background function takes a UUID instead of a `Document` object.

4. **When someone logs in with an email that doesn't exist, why does the code hash a password anyway?** What were the two numbers, and what attack does it defend against?

5. **401 vs 403** — which endpoint gave which today, and what does each actually mean?

6. **What's the weakness of `BackgroundTasks`, and what would you use instead at scale?** Why didn't you use it here?

7. **Why does `get_current_user` hit the database when the role is already in the token?** What does that cost and what does it buy?

---

# Tomorrow — Day 3

**The hardest day in the plan. Protect it.**

- Enable `pgvector`, add an `embedding` column to `Chunk`
- Generate embeddings during ingestion
- Similarity search returning the top chunks **with scores**
- A prompt that says: *answer only from the context, say so if it isn't there*
- **Then deliberately break it.** Ask something the documents don't cover. Watch it invent an answer.

**That failure is the best interview story in this whole project. Write down exactly what you saw.**

**Before starting:** get a Gemini API key. Groq has no embeddings endpoint (noted in the Day 0 log), so Day 3 needs a second provider. Don't spend the first hour of the hardest day on account setup.