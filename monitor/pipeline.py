"""
Triage pipeline (Phase 8E): batch-process cases through the full monitor
stack (Layers 1+2) and split them into an investigation queue vs. auto-
dismissed, so the expensive LangGraph agent only runs on flagged cases.

No LLM here — this is the cheap deterministic/statistical/ML gate.
"""

from __future__ import annotations

import time

from monitor.scorer import run_detection


def process_case(case: dict) -> dict:
    """Run the full detection stack over one case and recommend an action."""
    t0 = time.perf_counter()
    detection = run_detection(case)
    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))

    above = detection["above_threshold"]
    return {
        "case_id": case.get("case_id", "unknown"),
        "customer_name": case.get("customer", {}).get("name", "unknown"),
        "risk_score": detection["risk_score"],
        "above_threshold": above,
        "typology_flags": detection["typology_flags"],
        "graph_analysis": detection["graph_analysis"],
        "behavioral_analysis": detection["behavioral_analysis"],
        "anomaly_analysis": detection["anomaly_analysis"],
        "recommended_action": "INVESTIGATE" if above else "AUTO_DISMISS",
        "processing_time_ms": elapsed_ms,
    }


def process_batch(cases: list[dict]) -> dict:
    """Triage a batch: build the prioritized queue + lightweight dismissed list."""
    t0 = time.perf_counter()
    results = [process_case(c) for c in cases]
    total = len(results)

    flagged = [r for r in results if r["above_threshold"]]
    dismissed = [r for r in results if not r["above_threshold"]]

    triage_queue = sorted(flagged, key=lambda r: r["risk_score"], reverse=True)
    dismissed_cases = [
        {
            "case_id": r["case_id"],
            "customer_name": r["customer_name"],
            "risk_score": r["risk_score"],
        }
        for r in dismissed
    ]

    fp_reduction = round((len(dismissed) / total) * 100, 1) if total else 0.0

    return {
        "total_cases": total,
        "flagged_for_investigation": len(flagged),
        "auto_dismissed": len(dismissed),
        "false_positive_reduction_pct": fp_reduction,
        "triage_queue": triage_queue,
        "dismissed_cases": dismissed_cases,
        "processing_time_seconds": round(time.perf_counter() - t0, 3),
    }
