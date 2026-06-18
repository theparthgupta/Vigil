"""
Layer 1 scorer: run every typology detector over a case and combine the
flags into a single risk score.

No LLM. Pure aggregation over the deterministic detectors in typologies.py.
"""

from __future__ import annotations

import os

from monitor.behavioral import detect_behavioral_anomaly
from monitor.graph import run_graph_analysis
from monitor.typologies import (
    detect_dormant_reactivation,
    detect_geographic_anomaly,
    detect_high_risk_sector_spike,
    detect_rapid_passthrough,
    detect_round_trip,
    detect_sanctions_hit,
    detect_smurfing_network,
    detect_structuring,
    detect_upi_micro_structuring,
    detect_velocity_spike,
)

_DETECTORS = [
    detect_structuring,
    detect_rapid_passthrough,
    detect_sanctions_hit,
    detect_round_trip,
    detect_velocity_spike,
    detect_dormant_reactivation,
    detect_smurfing_network,
    detect_high_risk_sector_spike,
    detect_upi_micro_structuring,
    detect_geographic_anomaly,
]

# Severity weight per typology (used as the base of the risk score).
_WEIGHTS = {
    "sanctions_hit":          1.00,
    "structuring":            0.85,
    "rapid_passthrough":      0.85,
    "smurfing_network":       0.80,
    "round_trip":             0.75,
    "upi_micro_structuring":  0.75,
    "velocity_spike":         0.65,
    "dormant_reactivation":   0.65,
    "high_risk_sector_spike": 0.60,
    "geographic_anomaly":     0.55,
}

# Cases scoring at/above this are routed to the LLM investigation agent.
TRIAGE_THRESHOLD = float(os.getenv("VIGIL_THRESHOLD", "0.60"))


def _typology_flags(case: dict) -> list[dict]:
    """Run all 10 typology detectors over a case; return only the flagged results."""
    transactions = case.get("transactions", [])
    customer = case.get("customer", {})
    results = [detect(transactions, customer) for detect in _DETECTORS]
    return [r for r in results if r["flagged"]]


def compute_risk_score(typology_results: list[dict], graph_result: dict | None = None) -> float:
    """
    Combine flagged typologies (and optionally graph analysis) into a 0.0-1.0 score.

    Typology component:
      base        = highest severity weight among the flagged typologies
      compounding = 0.08 for each additional flag beyond the first
    If `graph_result` is given, fold in its score at 0.9 weight (heuristic on
    limited synthetic data); otherwise return the typology score (backwards-compatible).
    """
    if typology_results:
        base = max(_WEIGHTS.get(r["typology"], 0.0) for r in typology_results)
        compounding = 0.08 * (len(typology_results) - 1)
        typology_score = round(min(1.0, base + compounding), 4)
    else:
        typology_score = 0.0

    if graph_result is None:
        return typology_score

    graph_score = graph_result.get("graph_risk_score", 0.0)
    return round(min(1.0, max(typology_score, graph_score * 0.9)), 4)


def combine_scores(
    typology_score: float,
    graph_score: float,
    behavioral_score: float,
    has_sanctions: bool = False,
) -> float:
    """
    Blend the three detection layers into a single 0.0-1.0 risk score.

    Weighted sum (typology 0.60 / graph 0.25 / behavioral 0.15), then:
      OVERRIDE: a sanctions hit forces 1.0.
      FLOOR:    a strong typology score (>=0.85) keeps the result at >=0.75.
    """
    combined = min(1.0, typology_score * 0.60 + graph_score * 0.25 + behavioral_score * 0.15)
    if has_sanctions:
        combined = 1.0
    if typology_score >= 0.85:
        combined = max(combined, 0.75)
    return round(combined, 4)


def run_detection(case: dict) -> dict:
    """
    Full Layer-1 (typologies) + Layer-2A (graph) + Layer-2B (behavioral) detection.

    Returns the flagged typologies, the graph analysis, the behavioral analysis,
    the combined risk score, and whether it clears the triage threshold.
    """
    flags = _typology_flags(case)
    graph_analysis = run_graph_analysis(case)
    behavioral = detect_behavioral_anomaly(case)

    typology_score = compute_risk_score(flags, graph_analysis)
    graph_score = graph_analysis["graph_risk_score"]
    behavioral_score = behavioral["behavioral_score"] if behavioral["flagged"] else 0.0
    has_sanctions = any(f["typology"] == "sanctions_hit" for f in flags)

    risk_score = combine_scores(typology_score, graph_score, behavioral_score, has_sanctions)

    return {
        "typology_flags": flags,
        "graph_analysis": graph_analysis,
        "behavioral_analysis": behavioral,
        "risk_score": risk_score,
        "above_threshold": risk_score >= TRIAGE_THRESHOLD,
    }


def run_all_typologies(case: dict) -> list[dict]:
    """Backwards-compatible wrapper: just the flagged typologies (Layer 1)."""
    return run_detection(case)["typology_flags"]
