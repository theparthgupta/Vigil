"""
Tests for Layer-2B behavioral profiling (monitor/behavioral.py) and the
combined three-layer score in monitor/scorer.py.

Hand-crafted transaction lists; no JSON fixtures except test 6; no LLM/network.
"""

from datetime import datetime, timedelta

from monitor import run_detection
from monitor.behavioral import detect_behavioral_anomaly
from monitor.scorer import combine_scores

_BASE = datetime(2024, 1, 1)


def tx(amount, direction, channel, name, day):
    return {
        "id": f"t{day}_{name}", "customer_id": "c1", "amount_inr": float(amount),
        "timestamp": (_BASE + timedelta(days=day)).isoformat(),
        "counterparty_name": name, "counterparty_account": "00000000000000",
        "direction": direction, "channel": channel,
    }


def case_of(txns, business_type="sme"):
    return {
        "customer": {"name": "X", "business_type": business_type,
                     "stated_monthly_turnover_inr": 4_500_000, "prior_flags": 0},
        "transactions": txns,
    }


_KNOWN = ["Reliance", "Gati", "DMart"]


# ── 1. Insufficient history ───────────────────────────────────────────────────

def test_insufficient_history():
    txns = [tx(100_000, "debit", "UPI", _KNOWN[i % 3], i * 5) for i in range(8)]
    out = detect_behavioral_anomaly(case_of(txns))
    assert out["flagged"] is False
    assert out["evidence"]["reason"] == "insufficient_history"


# ── 2. Amount spike ───────────────────────────────────────────────────────────

def test_amount_spike_fires():
    hist = [tx(100_000 + (i % 3) * 1_000, "debit", "UPI", _KNOWN[i % 3], i * 5) for i in range(20)]
    recent = [tx(1_000_000, "debit", "UPI", _KNOWN[i % 3], 200 + i) for i in range(5)]
    out = detect_behavioral_anomaly(case_of(hist + recent))
    assert out["flagged"] is True
    assert out["evidence"]["amount_z"] >= 3.0


# ── 3. Stable customer ────────────────────────────────────────────────────────

def test_stable_customer_not_flagged():
    txns = [tx(100_000 + (i % 3) * 1_000, "debit", "UPI", _KNOWN[i % 3], i * 10) for i in range(25)]
    out = detect_behavioral_anomaly(case_of(txns))
    assert out["flagged"] is False


# ── 4. New counterparty surge ─────────────────────────────────────────────────

def test_new_counterparty_ratio_fires():
    hist = [tx(100_000, "debit", "UPI", _KNOWN[i % 3], i * 5) for i in range(20)]
    recent = [tx(100_000, "debit", "UPI", f"NewPayee{i}", 200 + i) for i in range(5)]
    out = detect_behavioral_anomaly(case_of(hist + recent))
    assert out["flagged"] is True
    assert out["evidence"]["new_counterparty_ratio"] == 1.0


# ── 5. Channel shift ──────────────────────────────────────────────────────────

def test_channel_shift_fires():
    hist = [tx(100_000, "debit", "UPI", _KNOWN[i % 3], i * 5) for i in range(20)]
    recent = [tx(100_000, "debit", "cash", _KNOWN[i % 3], 200 + i) for i in range(5)]
    out = detect_behavioral_anomaly(case_of(hist + recent))
    assert out["flagged"] is True
    assert out["evidence"]["channel_shift"] >= 0.9


# ── 6. run_detection exposes behavioral_analysis ──────────────────────────────

def test_run_detection_has_behavioral_key(cases_by_typology):
    out = run_detection(cases_by_typology["structuring"][0])
    assert "behavioral_analysis" in out
    assert out["behavioral_analysis"]["typology"] == "behavioral_anomaly"


# ── 7. Sanctions override forces 1.0 ──────────────────────────────────────────

def test_sanctions_override():
    txns = [
        tx(500_000, "debit", "NEFT", "Ali Hassan Mousa", 0),
        tx(200_000, "credit", "UPI", "Regular Client", 1),
        tx(150_000, "debit", "UPI", "Supplier", 2),
    ]
    assert run_detection(case_of(txns))["risk_score"] == 1.0


# ── 8. Score formula (anomaly layer defaults to 0 here) ───────────────────────

def test_combine_scores_formula():
    # 0.5*0.45 + 0.4*0.20 + 0.3*0.15 + 0.0*0.20 = 0.35
    assert combine_scores(0.5, 0.4, 0.3, 0.0) == 0.35
