"""
Layer 2A of the Vigil monitor: transaction knowledge-graph analysis.

Builds a directed graph of money flow around the customer ("SELF") and runs
four structural detectors (rings, layering chains, fan-out, intermediary
centrality). Pure NetworkX, no LLM.

Edge direction encodes money flow:
  credit  → counterparty --> SELF   (money in)
  debit   → SELF --> counterparty   (money out)
"""

from __future__ import annotations

from datetime import datetime

import networkx as nx

SELF = "SELF"


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


# ── Step 1: build the graph ───────────────────────────────────────────────────

def build_transaction_graph(case: dict) -> nx.DiGraph:
    """Money-flow DiGraph: SELF plus one node per unique counterparty."""
    G = nx.DiGraph()
    G.add_node(SELF)
    for t in case.get("transactions", []):
        other = t["counterparty_name"]
        G.add_node(other)
        attrs = {
            "amount_inr": float(t["amount_inr"]),
            "timestamp": t["timestamp"],
            "channel": t["channel"],
        }
        if t["direction"] == "credit":
            G.add_edge(other, SELF, **attrs)   # money in
        else:
            G.add_edge(SELF, other, **attrs)   # money out
    return G


# ── Step 2: detectors ─────────────────────────────────────────────────────────

def detect_structuring_ring(G: nx.DiGraph) -> dict:
    ref = "APG Typologies 2024 — Circular transaction networks"
    qualifying: list[list[str]] = []

    for cycle in nx.simple_cycles(G):
        if not (3 <= len(cycle) <= 5):
            continue
        amounts = [
            G[cycle[i]][cycle[(i + 1) % len(cycle)]]["amount_inr"]
            for i in range(len(cycle))
        ]
        lo, hi = min(amounts), max(amounts)
        if lo > 0 and hi <= 1.30 * lo:          # all within 30% of each other
            qualifying.append(cycle)

    flagged = bool(qualifying)
    return {
        "flagged": flagged,
        "typology": "structuring_ring",
        "cycles_found": qualifying,
        "confidence": 0.8 if flagged else 0.0,
        "evidence": {
            "cycle_count": len(qualifying),
            "example_cycle": qualifying[0] if qualifying else [],
        },
        "regulatory_ref": ref,
    }


def detect_layering_chain(G: nx.DiGraph) -> dict:
    ref = "FATF — Layering through multiple intermediaries"
    if SELF not in G:
        return _chain_result(ref, [])

    chains: list[dict] = []
    for target in G.nodes:
        if target == SELF:
            continue
        for path in nx.all_simple_paths(G, SELF, target, cutoff=5):
            hops = len(path) - 1
            if hops < 3:
                continue
            edges = [(path[i], path[i + 1]) for i in range(hops)]
            times = [_dt(G[u][v]["timestamp"]) for u, v in edges]
            within_48h = all(
                abs((times[i] - times[i - 1]).total_seconds()) <= 48 * 3600
                for i in range(1, len(times))
            )
            terminal = G.in_degree(path[-1]) == 1
            if within_48h and terminal:
                chains.append({
                    "path": path,
                    "amounts": [G[u][v]["amount_inr"] for u, v in edges],
                    "hops": hops,
                })

    return _chain_result(ref, chains)


def _chain_result(ref: str, chains: list[dict]) -> dict:
    flagged = bool(chains)
    return {
        "flagged": flagged,
        "typology": "layering_chain",
        "chains": chains,
        "confidence": 0.85 if flagged else 0.0,
        "evidence": {
            "chain_count": len(chains),
            "max_hops": max((c["hops"] for c in chains), default=0),
        },
        "regulatory_ref": ref,
    }


def detect_fan_out(G: nx.DiGraph) -> dict:
    ref = "APG Typologies 2024 — Fan-out layering pattern"
    new_recipients = (
        [n for n in G.successors(SELF) if G.in_degree(n) == 1] if SELF in G else []
    )
    flagged = len(new_recipients) >= 6
    return {
        "flagged": flagged,
        "typology": "fan_out",
        "hub_node": SELF,
        "new_recipient_count": len(new_recipients),
        "confidence": 0.75 if flagged else 0.0,
        "evidence": {"new_recipients": sorted(new_recipients)},
        "regulatory_ref": ref,
    }


def compute_centrality_flags(G: nx.DiGraph) -> dict:
    ref = "FATF — Intermediary account identification"
    scores = nx.betweenness_centrality(G, normalized=True)
    high = [
        {"node": n, "score": round(s, 3)}
        for n, s in scores.items()
        if n != SELF and s > 0.5
    ]
    high.sort(key=lambda d: d["score"], reverse=True)
    flagged = bool(high)
    return {
        "flagged": flagged,
        "typology": "high_centrality_node",
        "high_centrality_nodes": high,
        "confidence": 0.6 if flagged else 0.0,
        "evidence": {
            "node_count": len(high),
            "max_score": high[0]["score"] if high else 0.0,
        },
        "regulatory_ref": ref,
    }


# ── Step 3: orchestrator ──────────────────────────────────────────────────────

_GRAPH_WEIGHTS = {
    "structuring_ring": 1.0,
    "layering_chain": 0.9,
    "fan_out": 0.75,
    "high_centrality_node": 0.6,
}


def run_graph_analysis(case: dict) -> dict:
    G = build_transaction_graph(case)
    ring = detect_structuring_ring(G)
    chain = detect_layering_chain(G)
    fan = detect_fan_out(G)
    centrality = compute_centrality_flags(G)

    flagged = [r for r in (ring, chain, fan, centrality) if r["flagged"]]
    if flagged:
        base = max(_GRAPH_WEIGHTS[r["typology"]] for r in flagged)
        compounding = 0.08 * (len(flagged) - 1) if len(flagged) > 1 else 0.0
        score = round(min(1.0, base + compounding), 4)
    else:
        score = 0.0

    return {
        "structuring_ring": ring,
        "layering_chain": chain,
        "fan_out": fan,
        "centrality": centrality,
        "graph_risk_score": score,
        "graph_flagged_count": len(flagged),
    }
