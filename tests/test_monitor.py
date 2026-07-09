"""
Tests for the Layer-1 typology rule engine (monitor/).

Two tests per typology (one that should fire, one that should not) + scoring
and threshold tests. Hand-crafted minimal transaction lists; no JSON fixtures,
no LLM, no network (sanctions runs in local-list mode by default).
"""

from datetime import datetime, timedelta

from monitor import TRIAGE_THRESHOLD, compute_risk_score
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

_BASE = datetime(2024, 3, 1)


def tx(amount, direction, channel, name, day, hour=10):
    ts = (_BASE + timedelta(days=day, hours=hour)).isoformat()
    return {
        "id": f"t{day}_{hour}_{name}",
        "customer_id": "c1",
        "amount_inr": float(amount),
        "timestamp": ts,
        "counterparty_name": name,
        "counterparty_account": "00000000000000",
        "direction": direction,
        "channel": channel,
    }


def cust(business_type="sme", turnover=4_500_000):
    return {
        "id": "c1",
        "name": "Test Co",
        "business_type": business_type,
        "account_open_date": "2020-01-01T00:00:00",
        "stated_monthly_turnover_inr": float(turnover),
        "prior_flags": 0,
    }


# ── 1. structuring ────────────────────────────────────────────────────────────


def test_structuring_fires():
    txns = [
        tx(900_000, "credit", "cash", "Cash Deposit Mumbai", 0),
        tx(880_000, "credit", "cash", "Cash Deposit Pune", 5),
        tx(950_000, "credit", "cash", "Cash Deposit Delhi", 10),
    ]
    assert detect_structuring(txns, cust())["flagged"] is True


def test_structuring_quiet():
    txns = [
        tx(300_000, "credit", "cash", "Cash Deposit Mumbai", 0),
        tx(300_000, "credit", "cash", "Cash Deposit Pune", 5),
    ]
    assert detect_structuring(txns, cust())["flagged"] is False


# ── 2. rapid_passthrough ──────────────────────────────────────────────────────


def test_rapid_passthrough_fires():
    txns = [
        tx(2_000_000, "credit", "RTGS", "Source Ltd", 0, hour=9),
        tx(500_000, "debit", "NEFT", "Payee A", 0, hour=12),
        tx(500_000, "debit", "NEFT", "Payee B", 1, hour=9),
        tx(500_000, "debit", "UPI", "Payee C", 1, hour=12),
    ]
    out = detect_rapid_passthrough(txns, cust())
    assert out["flagged"] is True
    assert out["evidence"]["debit_count"] == 3


def test_rapid_passthrough_quiet():
    txns = [
        tx(2_000_000, "credit", "RTGS", "Source Ltd", 0, hour=9),
        tx(500_000, "debit", "NEFT", "Payee A", 0, hour=12),
    ]
    assert detect_rapid_passthrough(txns, cust())["flagged"] is False


# ── 3. sanctions_hit ──────────────────────────────────────────────────────────


def test_sanctions_hit_fires():
    txns = [tx(600_000, "debit", "NEFT", "Ali Hassan Mousa", 0)]
    assert detect_sanctions_hit(txns, cust())["flagged"] is True


def test_sanctions_hit_quiet():
    txns = [tx(600_000, "debit", "NEFT", "Mahesh Iyer", 0)]
    assert detect_sanctions_hit(txns, cust())["flagged"] is False


# ── 4. round_trip ─────────────────────────────────────────────────────────────


def test_round_trip_fires():
    txns = [
        tx(1_000_000, "debit", "RTGS", "Acme Corp", 0),
        tx(1_050_000, "credit", "RTGS", "Acme Corp", 5),
    ]
    assert detect_round_trip(txns, cust())["flagged"] is True


def test_round_trip_quiet():
    txns = [
        tx(1_000_000, "debit", "RTGS", "Acme Corp", 0),
        tx(1_000_000, "credit", "RTGS", "Other Inc", 5),
    ]
    assert detect_round_trip(txns, cust())["flagged"] is False


# ── 5. velocity_spike ─────────────────────────────────────────────────────────


def test_velocity_spike_fires():
    txns = [tx(10_000, "credit", "UPI", f"H{d}", d) for d in range(7)]  # old history
    txns += [tx(10_000, "credit", "UPI", f"R{k}", 100 + (k % 7)) for k in range(15)]  # recent burst
    out = detect_velocity_spike(txns, cust())
    assert out["flagged"] is True
    assert out["evidence"]["spike_ratio"] > 3.0


def test_velocity_spike_quiet():
    txns = [tx(10_000, "credit", "UPI", f"T{d}", d) for d in range(5)]  # < 20 → no baseline
    out = detect_velocity_spike(txns, cust())
    assert out["flagged"] is False
    assert out["evidence"]["reason"] == "insufficient_history"


# ── 6. dormant_reactivation ───────────────────────────────────────────────────


def test_dormant_reactivation_fires():
    txns = [
        tx(100_000, "credit", "UPI", "Opening", 0),
        tx(600_000, "credit", "RTGS", "Reactivation", 100),
        tx(200_000, "debit", "NEFT", "P1", 101),
        tx(200_000, "debit", "NEFT", "P2", 102),
    ]
    assert detect_dormant_reactivation(txns, cust())["flagged"] is True


def test_dormant_reactivation_quiet():
    txns = [
        tx(600_000, "credit", "RTGS", "A", 0),
        tx(200_000, "debit", "NEFT", "P1", 5),
        tx(200_000, "debit", "NEFT", "P2", 10),
    ]
    assert detect_dormant_reactivation(txns, cust())["flagged"] is False


# ── 7. smurfing_network ───────────────────────────────────────────────────────


def test_smurfing_network_fires():
    txns = [
        tx(900_000, "credit", "NEFT", "Sender One", 0),
        tx(880_000, "credit", "NEFT", "Sender Two", 1),
        tx(950_000, "credit", "NEFT", "Sender Three", 2),
    ]
    out = detect_smurfing_network(txns, cust())
    assert out["flagged"] is True
    assert len(out["evidence"]["sender_names"]) == 3


def test_smurfing_network_quiet():
    txns = [
        tx(900_000, "credit", "NEFT", "Sender One", 0),
        tx(880_000, "credit", "NEFT", "Sender One", 1),
        tx(950_000, "credit", "NEFT", "Sender One", 2),
    ]
    assert detect_smurfing_network(txns, cust())["flagged"] is False


# ── 8. high_risk_sector_spike ─────────────────────────────────────────────────


def test_high_risk_sector_spike_fires():
    txns = [tx(2_500_000, "credit", "RTGS", "Buyer", 0)]
    out = detect_high_risk_sector_spike(txns, cust("jewelry", turnover=1_000_000))
    assert out["flagged"] is True
    assert out["evidence"]["ratio"] == 2.5


def test_high_risk_sector_spike_quiet():
    txns = [tx(2_500_000, "credit", "RTGS", "Buyer", 0)]
    # retail is not a high-risk sector → no flag even with high volume
    assert (
        detect_high_risk_sector_spike(txns, cust("retail", turnover=1_000_000))["flagged"] is False
    )


# ── 9. upi_micro_structuring ──────────────────────────────────────────────────


def test_upi_micro_structuring_fires():
    senders = [f"S{i}" for i in range(8)]
    txns = [tx(60_000, "credit", "UPI", senders[i % 8], i % 7) for i in range(16)]
    out = detect_upi_micro_structuring(txns, cust())
    assert out["flagged"] is True
    assert out["evidence"]["unique_sender_count"] >= 8


def test_upi_micro_structuring_quiet():
    txns = [tx(60_000, "credit", "UPI", f"S{i}", i) for i in range(3)]
    assert detect_upi_micro_structuring(txns, cust())["flagged"] is False


# ── 10. geographic_anomaly ────────────────────────────────────────────────────


def test_geographic_anomaly_fires():
    txns = [
        tx(100_000, "debit", "NEFT", "Kerala Spices", 0),
        tx(100_000, "debit", "NEFT", "Punjab Traders", 1),
        tx(100_000, "debit", "NEFT", "Gujarat Textiles", 2),
        tx(100_000, "debit", "NEFT", "Bengal Imports", 3),
    ]
    out = detect_geographic_anomaly(txns, cust("retail"))
    assert out["flagged"] is True
    assert out["evidence"]["state_count"] >= 4


def test_geographic_anomaly_quiet():
    txns = [
        tx(100_000, "debit", "NEFT", "Acme Corp", 0),
        tx(100_000, "debit", "NEFT", "Beta Ltd", 1),
    ]
    out = detect_geographic_anomaly(txns, cust("retail"))
    assert out["flagged"] is False
    assert out["evidence"]["reason"] == "state_inference_unavailable"


# ── Scoring + threshold ───────────────────────────────────────────────────────


def _flag(typology):
    return {
        "flagged": True,
        "typology": typology,
        "confidence": 0.9,
        "evidence": {},
        "regulatory_ref": "",
    }


def test_score_single_flag_equals_weight():
    assert compute_risk_score([_flag("round_trip")]) == 0.75


def test_score_two_flags_between_single_and_one():
    score = compute_risk_score([_flag("round_trip"), _flag("velocity_spike")])
    assert 0.75 < score < 1.0


def test_score_sanctions_is_one():
    assert compute_risk_score([_flag("sanctions_hit")]) == 1.0


def test_score_five_flags_capped_at_one():
    flags = [
        _flag(t)
        for t in (
            "structuring",
            "round_trip",
            "velocity_spike",
            "dormant_reactivation",
            "geographic_anomaly",
        )
    ]
    assert compute_risk_score(flags) == 1.0


def test_score_no_flags_is_zero():
    assert compute_risk_score([]) == 0.0


def test_triage_threshold_default():
    assert TRIAGE_THRESHOLD == 0.60
