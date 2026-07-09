"""
Phase 4 agent tests — deterministic only (no LLM calls).

Covers:
 - route_after_reasoner truth table (the conditional loop logic)
 - investigator assembles evidence from a real train case using the real tools
 - state helpers and graph wiring

The live end-to-end LLM run is exercised by `python agent/run_one.py`, not here,
to keep the test suite fast and offline.
"""

import pytest

from agent.nodes import investigator, route_after_reasoner, ALL_TOOLS
from agent.state import initial_state


# ── Conditional edge truth table ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "confidence,passes,expected",
    [
        (0.40, 1, "investigate"),  # low conf, first pass done → loop once
        (0.59, 1, "investigate"),  # just below threshold → loop
        (0.60, 1, "report"),  # at threshold → report
        (0.90, 1, "report"),  # high conf → report
        (0.30, 2, "report"),  # low conf BUT max passes reached → report (no infinite loop)
        (0.10, 2, "report"),  # very low conf, capped → report
    ],
)
def test_route_after_reasoner(confidence, passes, expected):
    state = initial_state({"case_id": "x"})
    state["confidence"] = confidence
    state["investigation_passes"] = passes
    assert route_after_reasoner(state) == expected


def test_loop_is_bounded_to_one_extra_pass():
    """A case stuck at low confidence must still terminate at passes == 2."""
    state = initial_state({"case_id": "x"})
    state["confidence"] = 0.1
    # pass 1 → loop
    state["investigation_passes"] = 1
    assert route_after_reasoner(state) == "investigate"
    # pass 2 → must report, never loop again
    state["investigation_passes"] = 2
    assert route_after_reasoner(state) == "report"


# ── Investigator evidence assembly (real tools, no LLM) ───────────────────────


def test_investigator_assembles_evidence_structuring(cases_by_typology):
    case = cases_by_typology["structuring"][0]
    state = initial_state(case)
    state["tool_plan"] = list(ALL_TOOLS)

    out = investigator(state)
    ev = out["evidence"]

    assert {"profile", "patterns", "sanctions", "adverse_media"} <= ev.keys()
    assert ev["patterns"]["structuring_indicator"]["flagged"] is True
    assert ev["profile"]["customer_id"] == case["customer"]["id"]
    assert out["investigation_passes"] == 1


def test_investigator_detects_sanctions_hit(cases_by_typology):
    case = cases_by_typology["sanctions_hit"][0]
    state = initial_state(case)
    state["tool_plan"] = list(ALL_TOOLS)

    out = investigator(state)
    assert len(out["evidence"]["sanctions"]["hits"]) >= 1


def test_investigator_clean_case_no_sanctions(cases_by_typology):
    case = cases_by_typology["clean"][0]
    state = initial_state(case)
    state["tool_plan"] = list(ALL_TOOLS)

    out = investigator(state)
    assert out["evidence"]["sanctions"]["hits"] == []
    assert out["evidence"]["patterns"]["structuring_indicator"]["flagged"] is False


def test_investigator_respects_tool_plan(cases_by_typology):
    """Only planned tools run."""
    case = cases_by_typology["clean"][0]
    state = initial_state(case)
    state["tool_plan"] = ["profile", "patterns"]  # no sanctions / media

    out = investigator(state)
    ev = out["evidence"]
    assert "profile" in ev and "patterns" in ev
    assert "sanctions" not in ev
    assert "adverse_media" not in ev


def test_widen_pass_increments_counter(cases_by_typology):
    case = cases_by_typology["clean"][0]
    state = initial_state(case)
    state["tool_plan"] = ["profile", "patterns"]
    state["investigation_passes"] = 1  # simulate a re-pass

    out = investigator(state)
    assert out["investigation_passes"] == 2


# ── State helper ──────────────────────────────────────────────────────────────


def test_initial_state_has_all_fields():
    state = initial_state({"case_id": "x"})
    required = {
        "case",
        "evidence",
        "retrieved_passages",
        "decision",
        "confidence",
        "report",
        "investigation_steps",
        "tool_plan",
        "investigation_passes",
    }
    assert required <= state.keys()
    assert state["decision"] == ""
    assert state["confidence"] == 0.0
    assert state["investigation_passes"] == 0


# ── Graph wiring (compiles, no invocation) ────────────────────────────────────


def test_graph_compiles():
    from agent.graph import build_graph

    g = build_graph()
    assert g is not None
