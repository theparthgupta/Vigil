"""
Metrics for the Prahari evaluation harness (Phase 5).

Binary task: positive class = "suspicious" (agent should ESCALATE).
  - ground truth: case["ground_truth_label"] in {suspicious, clean}
  - prediction:   agent decision in {ESCALATE, DISMISS}
    ESCALATE -> predicted suspicious; DISMISS -> predicted clean.

The headline metric for an AML triage tool is the FALSE POSITIVE RATE on clean
cases — over-escalation buries analysts in noise and is the usual failure mode.
"""

from __future__ import annotations

import json
from pathlib import Path


def _is_positive_truth(row: dict) -> bool:
    return row["ground_truth_label"] == "suspicious"


def _is_positive_pred(row: dict) -> bool:
    return row["decision"] == "ESCALATE"


def compute_metrics(results: list[dict]) -> dict:
    """Compute the full metric bundle from a list of result rows."""
    tp = fp = fn = tn = 0
    for r in results:
        truth = _is_positive_truth(r)
        pred = _is_positive_pred(r)
        if truth and pred:
            tp += 1
        elif not truth and pred:
            fp += 1
        elif truth and not pred:
            fn += 1
        else:
            tn += 1

    total = len(results)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / total if total else 0.0
    # FPR on clean cases = FP / (all clean) = FP / (FP + TN)
    fpr_clean = fp / (fp + tn) if (fp + tn) else 0.0

    return {
        "total_cases": total,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "fpr_clean": round(fpr_clean, 4),
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "per_typology": _per_typology(results),
        "loop_fired_count": sum(1 for r in results if r.get("loop_fired")),
        "avg_latency_s": round(
            sum(r.get("latency_s", 0.0) for r in results) / total, 2
        ) if total else 0.0,
        "avg_confidence": round(
            sum(r.get("confidence", 0.0) for r in results) / total, 4
        ) if total else 0.0,
    }


def _per_typology(results: list[dict]) -> dict:
    """
    Per-typology breakdown.
    Suspicious typologies report detection rate (recall within the typology).
    Clean reports the false-positive rate (fraction wrongly ESCALATED).
    """
    buckets: dict[str, list[dict]] = {}
    for r in results:
        key = r["ground_truth_typology"] or "clean"
        buckets.setdefault(key, []).append(r)

    out = {}
    for typ, rows in sorted(buckets.items()):
        n = len(rows)
        escalated = sum(1 for r in rows if r["decision"] == "ESCALATE")
        if typ == "clean":
            out[typ] = {
                "n": n,
                "false_positives": escalated,
                "fpr": round(escalated / n, 4) if n else 0.0,
            }
        else:
            out[typ] = {
                "n": n,
                "detected": escalated,
                "detection_rate": round(escalated / n, 4) if n else 0.0,
            }
    return out


def format_report(metrics: dict, title: str = "EVALUATION REPORT") -> str:
    cm = metrics["confusion_matrix"]
    lines = [
        "=" * 60,
        f"  {title}",
        "=" * 60,
        f"  Cases evaluated : {metrics['total_cases']}",
        f"  Avg latency     : {metrics['avg_latency_s']}s   "
        f"Avg confidence: {metrics['avg_confidence']}",
        f"  Loop fired      : {metrics['loop_fired_count']} case(s)",
        "",
        "  OVERALL",
        f"    Precision : {metrics['precision']:.3f}",
        f"    Recall    : {metrics['recall']:.3f}",
        f"    F1        : {metrics['f1']:.3f}",
        f"    Accuracy  : {metrics['accuracy']:.3f}",
        "",
        f"  >> FPR on CLEAN cases (critical): {metrics['fpr_clean']:.3f} <<",
        "",
        "  CONFUSION MATRIX",
        "                 pred ESCALATE   pred DISMISS",
        f"    suspicious      {cm['tp']:>6}          {cm['fn']:>6}",
        f"    clean           {cm['fp']:>6}          {cm['tn']:>6}",
        "",
        "  PER-TYPOLOGY",
    ]
    for typ, d in metrics["per_typology"].items():
        if typ == "clean":
            lines.append(
                f"    {typ:<18} n={d['n']:<3} "
                f"false_positives={d['false_positives']} (FPR {d['fpr']:.3f})"
            )
        else:
            lines.append(
                f"    {typ:<18} n={d['n']:<3} "
                f"detected={d['detected']} (rate {d['detection_rate']:.3f})"
            )
    lines.append("=" * 60)
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("eval/results_baseline.json")
    results = json.loads(path.read_text(encoding="utf-8"))
    metrics = compute_metrics(results)
    print(format_report(metrics, title=f"REPORT — {path.name}"))
