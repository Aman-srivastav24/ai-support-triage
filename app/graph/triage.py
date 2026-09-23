"""Assembly of the triage graph.

Built per request because the retrieve node closes over that request's
database session. Compiling is cheap — no I/O, just wiring and validation.

    START → classify → retrieve → draft → score_confidence ─┬→ escalate     → END
                                                            └→ return_draft → END
"""

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.graph.nodes import classify, draft, make_retrieve_node, score_confidence
from app.graph.state import TriageState


def _escalate(state: TriageState) -> dict:
    """Terminal node for escalated tickets.

    Changes nothing: score_confidence already recorded the decision and the
    reason. It exists as a named step so the path is visible in traces and
    in the stream, and so later work (notifying a queue, emitting a metric)
    has somewhere to live.
    """
    return {}


def _return_draft(state: TriageState) -> dict:
    """Terminal node for tickets returned as a suggested draft."""
    return {}


def _route(state: TriageState) -> str:
    """Pick the branch after scoring.

    Reads state and returns a label; the mapping below turns that label into
    a destination. Routing is kept out of the state so no node can redirect
    the flow by writing to it.
    """
    return "escalate" if state["escalate"] else "return_draft"


def build_triage_graph(db: Session):
    """Compile the triage graph for one request."""
    graph = StateGraph(TriageState)

    graph.add_node("classify", classify)
    graph.add_node("retrieve", make_retrieve_node(db))
    graph.add_node("draft", draft)
    graph.add_node("score_confidence", score_confidence)
    graph.add_node("escalate", _escalate)
    graph.add_node("return_draft", _return_draft)

    graph.add_edge(START, "classify")
    graph.add_edge("classify", "retrieve")
    graph.add_edge("retrieve", "draft")
    graph.add_edge("draft", "score_confidence")

    graph.add_conditional_edges(
        "score_confidence",
        _route,
        {"escalate": "escalate", "return_draft": "return_draft"},
    )

    graph.add_edge("escalate", END)
    graph.add_edge("return_draft", END)

    return graph.compile()