"""
Layer 1 scorer: run every typology detector over a case and combine the
flags into a single risk score.

No LLM. Pure aggregation over the deterministic detectors in typologies.py.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from monitor.anomaly import detect_anomaly, load_or_train_model
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
    "sanctions_hit": 1.00,
    "structuring": 0.85,
    "rapid_passthrough": 0.85,
    "smurfing_network": 0.80,
    "round_trip": 0.75,
    "upi_micro_structuring": 0.75,
    "velocity_spike": 0.65,
    "dormant_reactivation": 0.65,
    "high_risk_sector_spike": 0.60,
    "geographic_anomaly": 0.55,
}

# Cases scoring at/above this are routed to the LLM investigation agent.
TRIAGE_THRESHOLD = float(os.getenv("VIGIL_THRESHOLD", "0.60"))

# Load the Isolation Forest once (trains + persists on first import if absent).
_ANOMALY_MODEL = load_or_train_model()

# ── Learned score fusion (Phase 11C) ──────────────────────────────────────────
# Logistic-regression weights trained on the SAML-D benchmark split
# (benchmarks/train_fusion.py). Plain JSON — readable and auditable, no pickle.
# If the file is absent the scorer falls back to the hand-tuned formula below.
_FUSION_PATH = Path(__file__).parent.parent / "benchmarks" / "fusion_weights.json"


def _load_fusion() -> dict | None:
    try:
        d = json.loads(_FUSION_PATH.read_text(encoding="utf-8"))
        return {
            "names": d["feature_names"],
            "coefs": d["coefficients"],
            "intercept": d["intercept"],
        }
    except Exception:
        return None


_FUSION = _load_fusion()


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
    anomaly_score: float = 0.0,
    has_sanctions: bool = False,
    flags: set[str] | None = None,
) -> float:
    """
    Blend the four detection layers into a single 0.0-1.0 risk score.

    Learned path (flags given + fusion weights present): logistic regression
    trained on the SAML-D split — sigmoid over the four layer scores plus
    per-typology indicators. Fully readable coefficients in
    benchmarks/fusion_weights.json.

    Fallback path (flags omitted or weights file missing): the original
    hand-tuned weighted sum (typology 0.45 / graph 0.20 / behavioral 0.15 /
    anomaly 0.20) with the typology>=0.85 -> >=0.75 floor.

    Either way, OVERRIDE: a sanctions hit forces 1.0 (applied after fusion —
    sanctions never fire in the training data, so it cannot be learned there).
    """
    if flags is not None and _FUSION is not None:
        feats = {
            "typology_score": typology_score,
            "graph_score": graph_score,
            "behavioral_score": behavioral_score,
            "anomaly_score": anomaly_score,
            "flag_structuring": float("structuring" in flags),
            "flag_fan_out": float("fan_out" in flags),
            "flag_velocity_spike": float("velocity_spike" in flags),
            "flag_sanctions_hit": float("sanctions_hit" in flags),
            "flag_rapid_passthrough": float("rapid_passthrough" in flags),
        }
        z = _FUSION["intercept"] + sum(
            _FUSION["coefs"][name] * feats[name] for name in _FUSION["names"]
        )
        combined = 1.0 / (1.0 + math.exp(-z))
    else:
        combined = min(
            1.0,
            (
                typology_score * 0.45
                + graph_score * 0.20
                + behavioral_score * 0.15
                + anomaly_score * 0.20
            ),
        )
        if typology_score >= 0.85:
            combined = max(combined, 0.75)

    if has_sanctions:
        combined = 1.0
    return round(combined, 4)


# Human-readable names for the fusion features (UI waterfall labels).
_FEATURE_LABELS = {
    "typology_score": "Typology rules score",
    "graph_score": "Graph structure score",
    "behavioral_score": "Behavioral deviation",
    "anomaly_score": "ML anomaly score",
    "flag_structuring": "Structuring flag",
    "flag_fan_out": "Fan-out flag",
    "flag_velocity_spike": "Velocity-spike flag",
    "flag_sanctions_hit": "Sanctions flag",
    "flag_rapid_passthrough": "Pass-through flag",
}


def explain_scores(
    typology_score: float,
    graph_score: float,
    behavioral_score: float,
    anomaly_score: float,
    has_sanctions: bool,
    flags: set[str],
    risk_score: float,
) -> dict:
    """
    Per-feature contribution breakdown for the UI waterfall. All arithmetic
    here, in Python — the frontend only renders it.
    """
    if _FUSION is not None:
        feats = {
            "typology_score": typology_score,
            "graph_score": graph_score,
            "behavioral_score": behavioral_score,
            "anomaly_score": anomaly_score,
            "flag_structuring": float("structuring" in flags),
            "flag_fan_out": float("fan_out" in flags),
            "flag_velocity_spike": float("velocity_spike" in flags),
            "flag_sanctions_hit": float("sanctions_hit" in flags),
            "flag_rapid_passthrough": float("rapid_passthrough" in flags),
        }
        items = [
            {
                "feature": name,
                "label": _FEATURE_LABELS[name],
                "value": round(feats[name], 4),
                "weight": _FUSION["coefs"][name],
                "contribution": round(_FUSION["coefs"][name] * feats[name], 4),
            }
            for name in _FUSION["names"]
            if feats[name] != 0.0
        ]
        items.sort(key=lambda d: -abs(d["contribution"]))
        return {
            "mode": "learned_fusion",
            "intercept": _FUSION["intercept"],
            "items": items,
            "sanctions_override": has_sanctions,
            "risk_score": risk_score,
        }

    # Hand-tuned fallback: the four weighted terms.
    hand = [
        ("typology_score", typology_score, 0.45),
        ("graph_score", graph_score, 0.20),
        ("behavioral_score", behavioral_score, 0.15),
        ("anomaly_score", anomaly_score, 0.20),
    ]
    return {
        "mode": "hand_tuned",
        "intercept": 0.0,
        "items": [
            {
                "feature": n,
                "label": _FEATURE_LABELS[n],
                "value": round(v, 4),
                "weight": w,
                "contribution": round(v * w, 4),
            }
            for n, v, w in hand
            if v != 0.0
        ],
        "sanctions_override": has_sanctions,
        "risk_score": risk_score,
    }


def run_detection(case: dict) -> dict:
    """
    Full Layer-1 (typologies) + Layer-2A (graph) + Layer-2B (behavioral) detection.

    Returns the flagged typologies, the graph analysis, the behavioral analysis,
    the ML anomaly analysis, the combined risk score, and whether it clears the
    triage threshold.
    """
    flags = _typology_flags(case)
    graph_analysis = run_graph_analysis(case)
    behavioral = detect_behavioral_anomaly(case)
    anomaly = detect_anomaly(case, model=_ANOMALY_MODEL)

    typology_score = compute_risk_score(flags, graph_analysis)
    graph_score = graph_analysis["graph_risk_score"]
    behavioral_score = behavioral["behavioral_score"] if behavioral["flagged"] else 0.0
    anomaly_score = anomaly["anomaly_score"] if anomaly["flagged"] else 0.0
    has_sanctions = any(f["typology"] == "sanctions_hit" for f in flags)

    fired = {f["typology"] for f in flags}
    if graph_analysis["fan_out"]["flagged"]:
        fired.add("fan_out")

    risk_score = combine_scores(
        typology_score,
        graph_score,
        behavioral_score,
        anomaly_score,
        has_sanctions,
        flags=fired,
    )

    return {
        "typology_flags": flags,
        "graph_analysis": graph_analysis,
        "behavioral_analysis": behavioral,
        "anomaly_analysis": anomaly,
        # Per-layer inputs to combine_scores, for UI explainability (Phase 10B).
        "layer_scores": {
            "typology": typology_score,
            "graph": graph_score,
            "behavioral": behavioral_score,
            "anomaly": anomaly_score,
        },
        # Per-feature contribution breakdown for the UI waterfall (Phase 12).
        "score_explanation": explain_scores(
            typology_score,
            graph_score,
            behavioral_score,
            anomaly_score,
            has_sanctions,
            fired,
            risk_score,
        ),
        "risk_score": risk_score,
        "above_threshold": bool(risk_score >= TRIAGE_THRESHOLD),
    }


def run_all_typologies(case: dict) -> list[dict]:
    """Backwards-compatible wrapper: just the flagged typologies (Layer 1)."""
    return run_detection(case)["typology_flags"]
