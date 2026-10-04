"""Day 6 eval: retrieval accuracy and escalation on a hand-labelled ticket set.

Run from project root:  python evals/run_evals.py [limit]

Calls the REAL embedder and LLM, so it costs API quota and results can vary
between runs. Deliberately not part of pytest.
"""

import os

# Settings are read once, at the first import of `app`, and environment
# variables take priority over .env. So this must run before any app import.
# Redis database 2 is reserved for evals: 0 is dev, 15 is pytest.
os.environ["REDIS_URL"] = "redis://localhost:6379/2"

import json  # noqa: E402  (imports below must come after the line above)
import sys  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

import redis  # noqa: E402
import subprocess  # noqa: E402
from dataclasses import asdict  # noqa: E402
from datetime import datetime  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.graph.nodes import SIMILARITY_FLOOR, TOP_K, _build_query  # noqa: E402
from app.graph.triage import build_triage_graph  # noqa: E402
from app.schemas.classification import TicketCategory  # noqa: E402
from app.services.providers import GeminiEmbedder, GroqLLM  # noqa: E402
from app.services.retrieval import search_chunks  # noqa: E402

TICKETS_PATH = Path(__file__).parent / "tickets.jsonl"

# Eval labels are short names; retrieval returns document titles.
# Checked against the local database on Day 6.
LABEL_TO_TITLE = {
    "billing": "Billing and Payments",
    "troubleshooting": "Troubleshooting",
    "accounts": "Accounts and Delivery",
}

# Seconds between tickets. Each ticket makes up to two Groq calls; this keeps
# a full run well under free-tier per-minute limits.
# Groq free tier for openai/gpt-oss-20b: 8,000 tokens per minute (the binding
# limit; 30 RPM is not). A ticket is roughly 2,500 tokens (estimate: classify
# ~300 + draft with 3 chunks and reasoning ~2,000), so ~3 tickets per minute.
# 25 s gives headroom for reasoning-token variance.
PAUSE_SECONDS = 25.0

# If a ticket still hits a 429, the per-minute bucket refills fully in 60 s.
RETRY_WAIT_SECONDS = 60.0
RESULTS_DIR = Path(__file__).parent / "results"

@dataclass
class TicketResult:
    """Everything observed for one ticket. Fields stay None if a step failed."""

    ticket_id: int
    kind: str
    label: str
    top1_title: str | None = None
    top1_score: float | None = None
    hit: bool | None = None  # None for "none" tickets: not scored on retrieval
    category: str | None = None
    chunks_kept: int | None = None
    escalated: bool | None = None
    reason: str | None = None
    draft: str | None = None
    error: str | None = None


def check_environment_and_reset_cache() -> None:
    """Refuse to run anywhere but local, then empty the eval cache."""
    settings = get_settings()

    db_url = settings.database_url
    if "localhost" not in db_url and "127.0.0.1" not in db_url:
        raise SystemExit("Refusing to run: DATABASE_URL is not local.")

    redis_url = settings.redis_url
    if not redis_url.endswith("/2"):
        raise SystemExit(f"Refusing to run: REDIS_URL resolved to {redis_url!r}, expected database 2.")

    client = redis.Redis.from_url(redis_url)
    try:
        client.ping()
        client.flushdb()
    finally:
        client.close()


def load_tickets() -> list[dict]:
    """Read the eval set and reject any label the script can't score."""
    tickets = [
        json.loads(line)
        for line in TICKETS_PATH.read_text().splitlines()
        if line.strip()
    ]
    for t in tickets:
        if t["label"] != "none" and t["label"] not in LABEL_TO_TITLE:
            raise SystemExit(f"Ticket {t['id']} has unknown label {t['label']!r}.")
    return tickets


def evaluate_ticket(db, graph, embedder, ticket: dict) -> TicketResult:
    """Measure retrieval on the raw ranking, then run the full pipeline."""
    result = TicketResult(ticket_id=ticket["id"], kind=ticket["kind"], label=ticket["label"])
    ticket_input = {"subject": ticket["subject"], "body": ticket["body"]}

    try:
        # 1. Retrieval, on the RAW ranking: before the similarity floor drops anything.
        ranked = search_chunks(db, _build_query(ticket_input), embedder=embedder, top_k=TOP_K)
        if not ranked:
            raise RuntimeError("search returned no chunks")
        top1 = ranked[0]
        result.top1_title = top1.document_title
        result.top1_score = top1.similarity
        if ticket["label"] != "none":
            result.hit = top1.document_title == LABEL_TO_TITLE[ticket["label"]]

        # 2. The full pipeline, for escalation. Writes nothing to the database.
        final = graph.invoke({"ticket_id": uuid.uuid4(), **ticket_input})
        result.category = final["category"].value
        result.chunks_kept = len(final["chunks"])
        result.escalated = final["escalate"]
        result.reason = final["escalation_reason"]
        result.draft = final["draft"]
    except Exception as exc:  # record and carry on: one failure must not lose the run
        result.error = f"{type(exc).__name__}: {exc}"

    return result


def print_row(r: TicketResult) -> None:
    """One line per ticket, plus a reason line and any warning."""
    if r.error:
        print(f"#{r.ticket_id:<3} ERROR  {r.error}")
        return

    retrieval = "-   " if r.hit is None else ("HIT " if r.hit else "MISS")
    outcome = "ESCALATED" if r.escalated else "drafted"
    print(
        f"#{r.ticket_id:<3} {r.kind:<9} {r.label:<16} {retrieval} "
        f"top1={r.top1_title} ({r.top1_score:.4f})  kept={r.chunks_kept}  "
        f"{r.category:<10} {outcome}"
    )
    if r.reason:
        print(f"      reason: {r.reason}")
    if r.label != "none" and r.category == TicketCategory.OTHER.value:
        print("      WARN: answerable ticket classified OTHER, check the log for a classification failure")

def ratio(n: int, d: int) -> str:
    """'11/14 = 79%', or '0/0 (n/a)' when there is nothing to divide by."""
    return f"{n}/{d} = {n / d:.0%}" if d else f"{n}/{d} (n/a)"


def summarise(results: list[TicketResult]) -> dict:
    """Compute every number from raw rows. Errored tickets are counted, never scored."""
    ok = [r for r in results if r.error is None]
    answerable = [r for r in ok if r.label != "none"]
    unanswerable = [r for r in ok if r.label == "none"]
    hits = [r for r in answerable if r.hit]

    return {
        "tickets": len(results),
        "errors": [r.ticket_id for r in results if r.error],
        "top1_hits": len(hits),
        "answerable": len(answerable),
        "by_kind": {
            kind: [sum(r.hit for r in answerable if r.kind == kind),
                   sum(1 for r in answerable if r.kind == kind)]
            for kind in ("easy", "reworded", "code")
        },
        "retrieval_misses": [r.ticket_id for r in answerable if not r.hit],
        "hits_below_floor": [r.ticket_id for r in hits if r.top1_score < SIMILARITY_FLOOR],
        "escalated": sum(r.escalated for r in ok),
        "scored": len(ok),
        "caught": sum(r.escalated for r in unanswerable),
        "unanswerable": len(unanswerable),
        "over_escalated": [r.ticket_id for r in answerable if r.escalated],
        "missed_escalations": [r.ticket_id for r in unanswerable if not r.escalated],
        "answerable_classified_other": [
            r.ticket_id for r in answerable if r.category == TicketCategory.OTHER.value
        ],
    }


def print_summary(s: dict) -> None:
    print("\n" + "=" * 70)
    print(f"retrieval top-1   {ratio(s['top1_hits'], s['answerable'])}   (random baseline 33%)")
    print("  by kind:        " + ", ".join(f"{k} {h}/{n}" for k, (h, n) in s["by_kind"].items()))
    print(f"  misses:         {s['retrieval_misses']}")
    print(f"  hits below floor (pipeline discarded the right doc): {s['hits_below_floor']}")
    print(f"escalation rate   {ratio(s['escalated'], s['scored'])}   (context only)")
    print(f"catch rate        {ratio(s['caught'], s['unanswerable'])}   (none tickets escalated, higher is better)")
    print(f"over-escalation   {ratio(len(s['over_escalated']), s['answerable'])}   (answerable escalated, lower is better)")
    print(f"  over-escalated: {s['over_escalated']}")
    print(f"  MISSED escalations, read these drafts: {s['missed_escalations']}")
    print("=" * 70)
    if s["errors"]:
        print(f"RUN INCOMPLETE: tickets {s['errors']} errored. Do not record these numbers.")
    if s["answerable_classified_other"]:
        print(f"CHECK: answerable tickets {s['answerable_classified_other']} classified OTHER.")


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def save_run(results: list[TicketResult], summary: dict) -> Path:
    """Write metadata, summary and every row to evals/results/run-<timestamp>.json."""
    RESULTS_DIR.mkdir(exist_ok=True)
    started = datetime.now()
    path = RESULTS_DIR / f"run-{started:%Y%m%d-%H%M%S}.json"
    payload = {
        "meta": {
            "saved_at": started.isoformat(timespec="seconds"),
            "git_commit": _git("rev-parse", "--short", "HEAD"),
            "uncommitted_changes": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "groq_model": get_settings().groq_model,
            "top_k": TOP_K,
            "similarity_floor": SIMILARITY_FLOOR,
        },
        "summary": summary,
        "results": [asdict(r) for r in results],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path
if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None

    check_environment_and_reset_cache()
    tickets = load_tickets()[:limit]
    print(f"environment ok, eval cache flushed, running {len(tickets)} tickets\n")

    db = SessionLocal()
    try:
        embedder = GeminiEmbedder()
        graph = build_triage_graph(db, llm=GroqLLM(), embedder=embedder)

        results: list[TicketResult] = []
        for i, ticket in enumerate(tickets):
            if i:
                time.sleep(PAUSE_SECONDS)
            r = evaluate_ticket(db, graph, embedder, ticket)
            if r.error and "429" in r.error:
                print(f"#{ticket['id']:<3} rate-limited, waiting {RETRY_WAIT_SECONDS:.0f}s, retrying once")
                time.sleep(RETRY_WAIT_SECONDS)
                r = evaluate_ticket(db, graph, embedder, ticket)
            print_row(r)
            results.append(r)
    finally:
        db.close()
    summary = summarise(results)
    print_summary(summary)
    print(f"\nsaved: {save_run(results, summary)}")    