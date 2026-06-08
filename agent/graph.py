"""
LangGraph assembly for the Vigil agent (Phase 4).

    START → planner → investigator → reasoner → [conditional] → reporter → END
                           ↑__________________________|
                           (loop once if confidence < 0.6)
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent.nodes import (
    investigator,
    planner,
    reasoner,
    reporter,
    route_after_reasoner,
)
from agent.state import VigilState


def build_graph():
    """Build and compile the Vigil investigation graph."""
    g = StateGraph(VigilState)

    g.add_node("planner", planner)
    g.add_node("investigator", investigator)
    g.add_node("reasoner", reasoner)
    g.add_node("reporter", reporter)

    g.add_edge(START, "planner")
    g.add_edge("planner", "investigator")
    g.add_edge("investigator", "reasoner")
    g.add_conditional_edges(
        "reasoner",
        route_after_reasoner,
        {"investigate": "investigator", "report": "reporter"},
    )
    g.add_edge("reporter", END)

    return g.compile()


# Module-level compiled graph for reuse (runner, API, eval)
graph = build_graph()
