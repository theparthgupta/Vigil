"""Tests for eval/metrics.py — pure computation, no LLM."""

from eval.metrics import compute_metrics


def _row(label, typology, decision, **kw):
    return {
        "ground_truth_label": label,
        "ground_truth_typology": typology,
        "decision": decision,
        "confidence": kw.get("confidence", 0.8),
        "latency_s": kw.get("latency_s", 1.0),
        "loop_fired": kw.get("loop_fired", False),
    }


def test_perfect_classifier():
    results = [
        _row("suspicious", "structuring", "ESCALATE"),
        _row("suspicious", "sanctions_hit", "ESCALATE"),
        _row("clean", None, "DISMISS"),
        _row("clean", None, "DISMISS"),
    ]
    m = compute_metrics(results)
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["f1"] == 1.0
    assert m["accuracy"] == 1.0
    assert m["fpr_clean"] == 0.0
    assert m["confusion_matrix"] == {"tp": 2, "fp": 0, "fn": 0, "tn": 2}


def test_fpr_on_clean_is_computed():
    # 2 clean cases, 1 wrongly escalated -> FPR 0.5
    results = [
        _row("clean", None, "ESCALATE"),
        _row("clean", None, "DISMISS"),
        _row("suspicious", "structuring", "ESCALATE"),
    ]
    m = compute_metrics(results)
    assert m["fpr_clean"] == 0.5
    assert m["confusion_matrix"]["fp"] == 1
    assert m["confusion_matrix"]["tn"] == 1


def test_recall_with_false_negatives():
    # 2 suspicious, 1 missed -> recall 0.5
    results = [
        _row("suspicious", "structuring", "ESCALATE"),
        _row("suspicious", "rapid_passthrough", "DISMISS"),
        _row("clean", None, "DISMISS"),
    ]
    m = compute_metrics(results)
    assert m["recall"] == 0.5
    assert m["confusion_matrix"]["fn"] == 1


def test_precision_with_false_positives():
    # 1 TP, 1 FP -> precision 0.5
    results = [
        _row("suspicious", "structuring", "ESCALATE"),
        _row("clean", None, "ESCALATE"),
    ]
    m = compute_metrics(results)
    assert m["precision"] == 0.5


def test_per_typology_breakdown():
    results = [
        _row("suspicious", "structuring", "ESCALATE"),
        _row("suspicious", "structuring", "DISMISS"),  # missed
        _row("suspicious", "sanctions_hit", "ESCALATE"),
        _row("clean", None, "ESCALATE"),  # false positive
        _row("clean", None, "DISMISS"),
    ]
    m = compute_metrics(results)
    pt = m["per_typology"]
    assert pt["structuring"]["detection_rate"] == 0.5
    assert pt["sanctions_hit"]["detection_rate"] == 1.0
    assert pt["clean"]["fpr"] == 0.5
    assert pt["clean"]["false_positives"] == 1


def test_aggregate_helpers():
    results = [
        _row("suspicious", "structuring", "ESCALATE", latency_s=2.0, loop_fired=True),
        _row("clean", None, "DISMISS", latency_s=4.0, loop_fired=False),
    ]
    m = compute_metrics(results)
    assert m["loop_fired_count"] == 1
    assert m["avg_latency_s"] == 3.0
