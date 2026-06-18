"""
Tests for the Layer-2A transaction knowledge graph (monitor/graph.py).

Tests 1-4 build DiGraphs by hand; 5-6 use real cases from the TRAIN split via
the cases_by_typology fixture; 7-8 cover the orchestrator shape and backwards
compatibility. No LLM, no network.
"""

from datetime import datetime, timedelta

import networkx as nx

from monitor import run_all_typologies, run_detection
from monitor.graph import (
    detect_fan_out,
    detect_structuring_ring,
    run_graph_analysis,
)

_BASE = datetime(2024, 3, 1)


def _edge(G, u, v, amount=100_000, day=0):
    G.add_edge(u, v, amount_inr=float(amount),
               timestamp=(_BASE + timedelta(days=day)).isoformat(), channel="NEFT")


def tx(amount, direction, name, day):
    return {
        "id": f"t{day}_{name}", "customer_id": "c1", "amount_inr": float(amount),
        "timestamp": (_BASE + timedelta(days=day)).isoformat(),
        "counterparty_name": name, "counterparty_account": "00000000000000",
        "direction": direction, "channel": "NEFT",
    }


# ── 1. Structuring ring fires ─────────────────────────────────────────────────

def test_structuring_ring_fires():
    G = nx.DiGraph()
    _edge(G, "SELF", "A", 100_000)
    _edge(G, "A", "B", 105_000)      # within 30% of each other
    _edge(G, "B", "SELF", 110_000)
    out = detect_structuring_ring(G)
    assert out["flagged"] is True
    assert out["evidence"]["cycle_count"] >= 1


# ── 2. No ring on a linear graph ──────────────────────────────────────────────

def test_no_ring_on_linear_graph():
    G = nx.DiGraph()
    _edge(G, "SELF", "A")
    _edge(G, "A", "B")               # SELF → A → B, no cycle back
    assert detect_structuring_ring(G)["flagged"] is False


# ── 3. Fan-out fires ──────────────────────────────────────────────────────────

def test_fan_out_fires():
    G = nx.DiGraph()
    for i in range(7):
        _edge(G, "SELF", f"R{i}")    # 7 distinct new recipients (in-degree 1)
    out = detect_fan_out(G)
    assert out["flagged"] is True
    assert out["new_recipient_count"] == 7


# ── 4. Fan-out below threshold ────────────────────────────────────────────────

def test_fan_out_below_threshold():
    G = nx.DiGraph()
    for i in range(4):
        _edge(G, "SELF", f"R{i}")    # only 4 recipients, threshold is 6
    assert detect_fan_out(G)["flagged"] is False


# ── 5. Rapid pass-through case exhibits fan-out ───────────────────────────────

def test_rapid_passthrough_triggers_fan_out(cases_by_typology):
    rpt = cases_by_typology["rapid_passthrough"]
    assert any(run_graph_analysis(c)["fan_out"]["flagged"] for c in rpt)


# ── 6. A clean case scores zero on the graph ──────────────────────────────────

def test_clean_case_low_graph_score(cases_by_typology):
    scores = [run_graph_analysis(c)["graph_risk_score"] for c in cases_by_typology["clean"]]
    assert min(scores) == 0.0


# ── 7. run_detection shape ────────────────────────────────────────────────────

def test_run_detection_shape():
    case = {
        "customer": {"name": "X", "business_type": "sme",
                     "stated_monthly_turnover_inr": 4_500_000, "prior_flags": 0},
        "transactions": [
            tx(900_000, "credit", "cash", 0),
            tx(880_000, "credit", "cash", 5),
            tx(950_000, "credit", "cash", 10),
        ],
    }
    out = run_detection(case)
    assert {"typology_flags", "graph_analysis", "risk_score", "above_threshold"} <= set(out.keys())
    assert isinstance(out["typology_flags"], list)
    assert isinstance(out["graph_analysis"], dict)
    assert isinstance(out["risk_score"], float)
    assert isinstance(out["above_threshold"], bool)


# ── 8. Backwards compatibility ────────────────────────────────────────────────

def test_run_all_typologies_backwards_compatible():
    case = {
        "customer": {"name": "X", "business_type": "sme",
                     "stated_monthly_turnover_inr": 4_500_000, "prior_flags": 0},
        "transactions": [tx(900_000, "credit", "cash", 0)],
    }
    result = run_all_typologies(case)
    assert isinstance(result, list)
