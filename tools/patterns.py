"""
Tool 2: Deterministic transaction pattern analyser.

Pure Python arithmetic — no LLM. Accepts a list of TransactionRecord dicts
(as loaded from JSON). Returns all features as a plain JSON-serialisable dict.

Regulatory anchors:
  - CTR threshold Rs.10 lakh (PMLA 2002, Section 12)
  - Structuring = breaking amounts to stay below CTR threshold (FATF Rec. 29)
  - Rapid pass-through = layering typology (PMLA Section 3; FATF South Asia 2021)
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta

# ── Structuring thresholds ────────────────────────────────────────────────────
# Band: Rs.8L–Rs.9.99L cash deposits. Lower bound is Rs.8L (not Rs.9L) because
# our synthetic data contains deposits from Rs.8.5L up; using Rs.9L would miss
# Rs.8.5L-Rs.8.99L deposits. A real deployment can tighten this.
_STRUCT_LOW_INR = 800_000  # Rs.8 lakh
_STRUCT_HIGH_INR = 999_999  # just under Rs.10 lakh CTR threshold
_STRUCT_WINDOW_DAYS = 30
_STRUCT_MIN_COUNT = 3  # FATF: ≥3 such deposits → structuring indicator

# ── Rapid pass-through thresholds ────────────────────────────────────────────
_PASS_MIN_CREDIT_INR = 1_000_000  # Rs.10 lakh minimum to be a "large" credit
_PASS_WINDOW_HOURS = 72
_PASS_MIN_DEBITS = 5
_PASS_MIN_RATIO = 0.80  # ≥80% of credit debited out


def analyze_patterns(transactions: list[dict]) -> dict:
    """
    Extract AML-relevant features from a list of TransactionRecord dicts.

    Returns:
        total_transactions          int
        date_range_days             int
        avg_amount_inr              float
        median_amount_inr           float
        total_credits_inr           float
        total_debits_inr            float
        cash_credit_total_inr       float
        velocity_7d                 int     # txns in last 7 days of window
        velocity_30d                int
        velocity_90d                int
        unique_counterparties       int
        counterparty_diversity_ratio float  # unique / total
        structuring_indicator       dict
        rapid_passthrough_indicator dict
    """
    if not transactions:
        return _empty()

    txns = sorted(transactions, key=lambda t: _dt(t["timestamp"]))
    timestamps = [_dt(t["timestamp"]) for t in txns]
    amounts = [t["amount_inr"] for t in txns]
    most_recent = timestamps[-1]

    credits = [t for t in txns if t["direction"] == "credit"]
    debits = [t for t in txns if t["direction"] == "debit"]
    cash_cr = [t for t in credits if t["channel"] == "cash"]
    unique_cp = {t["counterparty_name"] for t in txns}

    return {
        "total_transactions": len(txns),
        "date_range_days": (most_recent - timestamps[0]).days,
        "avg_amount_inr": round(statistics.mean(amounts), 2),
        "median_amount_inr": round(statistics.median(amounts), 2),
        "total_credits_inr": round(sum(t["amount_inr"] for t in credits), 2),
        "total_debits_inr": round(sum(t["amount_inr"] for t in debits), 2),
        "cash_credit_total_inr": round(sum(t["amount_inr"] for t in cash_cr), 2),
        "velocity_7d": _velocity(timestamps, most_recent, 7),
        "velocity_30d": _velocity(timestamps, most_recent, 30),
        "velocity_90d": _velocity(timestamps, most_recent, 90),
        "unique_counterparties": len(unique_cp),
        "counterparty_diversity_ratio": round(len(unique_cp) / len(txns), 3),
        "structuring_indicator": _structuring(txns),
        "rapid_passthrough_indicator": _rapid_passthrough(txns),
    }


# ── Feature detectors ─────────────────────────────────────────────────────────


def _structuring(txns: list[dict]) -> dict:
    """
    Flag if ≥3 cash deposits in Rs.8L–Rs.9.99L fall within any 30-day window.
    PMLA s.12: reporting entity must file CTR for cash >= Rs.10 lakh.
    Structuring = deliberately splitting to avoid this threshold.
    """
    near = [
        t
        for t in txns
        if t["direction"] == "credit"
        and t["channel"] == "cash"
        and _STRUCT_LOW_INR <= t["amount_inr"] <= _STRUCT_HIGH_INR
    ]
    flagged = False
    if len(near) >= _STRUCT_MIN_COUNT:
        times = sorted(_dt(t["timestamp"]) for t in near)
        for start in times:
            end = start + timedelta(days=_STRUCT_WINDOW_DAYS)
            if sum(1 for ts in times if start <= ts <= end) >= _STRUCT_MIN_COUNT:
                flagged = True
                break

    return {
        "flagged": flagged,
        "near_threshold_cash_count": len(near),
        "window_days": _STRUCT_WINDOW_DAYS,
        "threshold_band_inr": [_STRUCT_LOW_INR, _STRUCT_HIGH_INR],
    }


def _rapid_passthrough(txns: list[dict]) -> dict:
    """
    Flag if a large credit is followed within 72 h by ≥5 debits to NEW payees
    totalling ≥80% of the credit. Classic layering indicator (FATF).
    'New' = counterparty not seen in any transaction before this credit.
    """
    sorted_txns = sorted(txns, key=lambda t: _dt(t["timestamp"]))
    seen_before: set[str] = set()

    for i, txn in enumerate(sorted_txns):
        if txn["direction"] != "credit" or txn["amount_inr"] < _PASS_MIN_CREDIT_INR:
            seen_before.add(txn["counterparty_name"])
            continue

        credit_amt = txn["amount_inr"]
        credit_ts = _dt(txn["timestamp"])
        window_end = credit_ts + timedelta(hours=_PASS_WINDOW_HOURS)
        prior = frozenset(seen_before)  # snapshot at moment of credit

        new_debits = [
            s
            for s in sorted_txns[i + 1 :]
            if _dt(s["timestamp"]) <= window_end
            and s["direction"] == "debit"
            and s["counterparty_name"] not in prior
        ]

        if len(new_debits) >= _PASS_MIN_DEBITS:
            ratio = sum(s["amount_inr"] for s in new_debits) / credit_amt
            if ratio >= _PASS_MIN_RATIO:
                return {
                    "flagged": True,
                    "trigger_credit_inr": round(credit_amt, 2),
                    "debit_count_within_72h": len(new_debits),
                    "passthrough_ratio": round(ratio, 3),
                }

        seen_before.add(txn["counterparty_name"])

    return {
        "flagged": False,
        "trigger_credit_inr": None,
        "debit_count_within_72h": None,
        "passthrough_ratio": None,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _velocity(timestamps: list[datetime], reference: datetime, days: int) -> int:
    cutoff = reference - timedelta(days=days)
    return sum(1 for ts in timestamps if ts >= cutoff)


def _empty() -> dict:
    return {
        "total_transactions": 0,
        "date_range_days": 0,
        "avg_amount_inr": 0.0,
        "median_amount_inr": 0.0,
        "total_credits_inr": 0.0,
        "total_debits_inr": 0.0,
        "cash_credit_total_inr": 0.0,
        "velocity_7d": 0,
        "velocity_30d": 0,
        "velocity_90d": 0,
        "unique_counterparties": 0,
        "counterparty_diversity_ratio": 0.0,
        "structuring_indicator": {
            "flagged": False,
            "near_threshold_cash_count": 0,
            "window_days": _STRUCT_WINDOW_DAYS,
            "threshold_band_inr": [_STRUCT_LOW_INR, _STRUCT_HIGH_INR],
        },
        "rapid_passthrough_indicator": {
            "flagged": False,
            "trigger_credit_inr": None,
            "debit_count_within_72h": None,
            "passthrough_ratio": None,
        },
    }
