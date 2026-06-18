"""
Layer 1 scorer: run every typology detector over a case and combine the
flags into a single risk score.

No LLM. Pure aggregation over the deterministic detectors in typologies.py.
"""

from __future__ import annotations

import os

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


def run_all_typologies(case: dict) -> list[dict]:
    """Run all 10 detectors over a case; return only the flagged results."""
    transactions = case.get("transactions", [])
    customer = case.get("customer", {})
    results = [detect(transactions, customer) for detect in _DETECTORS]
    return [r for r in results if r["flagged"]]


def compute_risk_score(typology_results: list[dict]) -> float:
    """
    Combine flagged typologies into a 0.0-1.0 risk score:
      base        = highest severity weight among the flagged typologies
      compounding = 0.08 for each additional flag beyond the first
    """
    if not typology_results:
        return 0.0
    base = max(_WEIGHTS.get(r["typology"], 0.0) for r in typology_results)
    compounding = 0.08 * (len(typology_results) - 1)
    return round(min(1.0, base + compounding), 4)
