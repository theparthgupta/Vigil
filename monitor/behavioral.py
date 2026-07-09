"""
Layer 2B of the Vigil monitor: behavioral profiling.

Builds a per-customer baseline from transaction history and flags the most
recent 30 days when they deviate sharply from it (amount/count z-scores,
channel-mix shift, new-counterparty surge). Pure stdlib statistics, no LLM.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _channel_dist(txns: list[dict]) -> dict:
    if not txns:
        return {}
    n = len(txns)
    out: dict[str, float] = {}
    for t in txns:
        out[t["channel"]] = out.get(t["channel"], 0.0) + 1
    return {k: v / n for k, v in out.items()}


def _credit_ratio(txns: list[dict]) -> float:
    if not txns:
        return 0.0
    return sum(1 for t in txns if t["direction"] == "credit") / len(txns)


# ── Step 1: baseline ──────────────────────────────────────────────────────────


def compute_baseline(transactions: list[dict]) -> dict | None:
    if len(transactions) < 15:
        return None

    txns = sorted(transactions, key=lambda t: _dt(t["timestamp"]))
    most_recent = _dt(txns[-1]["timestamp"])
    cutoff = most_recent - timedelta(days=30)
    history = [t for t in txns if _dt(t["timestamp"]) < cutoff]
    if len(history) < 10:
        return None

    amounts = [t["amount_inr"] for t in history]
    avg_amount = statistics.mean(amounts)
    std_amount = statistics.pstdev(amounts)
    if std_amount == 0.0:
        std_amount = avg_amount * 0.1

    # transactions per 30-day window across the history span
    ts_list = [_dt(t["timestamp"]) for t in history]
    start, end = ts_list[0], ts_list[-1]
    counts: list[int] = []
    i = 0
    while True:
        w0 = start + timedelta(days=30 * i)
        if w0 > end:
            break
        w1 = w0 + timedelta(days=30)
        counts.append(sum(1 for ts in ts_list if w0 <= ts < w1))
        i += 1
    if not counts:
        counts = [len(history)]
    avg_monthly = statistics.mean(counts)
    std_monthly = statistics.pstdev(counts) if len(counts) > 1 else 0.0
    if std_monthly == 0.0:
        std_monthly = 1.0

    return {
        "avg_amount_inr": avg_amount,
        "std_amount_inr": std_amount,
        "avg_monthly_txn_count": avg_monthly,
        "std_monthly_count": std_monthly,
        "channel_distribution": _channel_dist(history),
        "known_counterparties": {t["counterparty_name"] for t in history},
        "avg_credit_ratio": _credit_ratio(history),
    }


# ── Step 2: current window ────────────────────────────────────────────────────


def compute_current_window(transactions: list[dict], days: int = 30) -> dict:
    if not transactions:
        return {
            "current_count": 0,
            "current_avg_amount_inr": 0.0,
            "current_channel_dist": {},
            "new_counterparty_ratio": 0.0,
            "current_credit_ratio": 0.0,
        }

    txns = sorted(transactions, key=lambda t: _dt(t["timestamp"]))
    most_recent = _dt(txns[-1]["timestamp"])
    cutoff = most_recent - timedelta(days=days)
    current = [t for t in txns if _dt(t["timestamp"]) >= cutoff]
    known = {t["counterparty_name"] for t in txns if _dt(t["timestamp"]) < cutoff}

    if not current:
        return {
            "current_count": 0,
            "current_avg_amount_inr": 0.0,
            "current_channel_dist": {},
            "new_counterparty_ratio": 0.0,
            "current_credit_ratio": 0.0,
        }

    new = sum(1 for t in current if t["counterparty_name"] not in known)
    return {
        "current_count": len(current),
        "current_avg_amount_inr": statistics.mean(t["amount_inr"] for t in current),
        "current_channel_dist": _channel_dist(current),
        "new_counterparty_ratio": new / len(current),
        "current_credit_ratio": _credit_ratio(current),
    }


# ── Step 3: channel distance ──────────────────────────────────────────────────


def channel_distance(dist_a: dict, dist_b: dict) -> float:
    keys = set(dist_a) | set(dist_b)
    if not keys:
        return 0.0
    va = [dist_a.get(k, 0.0) for k in keys]
    vb = [dist_b.get(k, 0.0) for k in keys]
    na = math.sqrt(sum(x * x for x in va))
    nb = math.sqrt(sum(y * y for y in vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    cos = sum(x * y for x, y in zip(va, vb)) / (na * nb)
    return max(0.0, min(1.0, 1.0 - cos))


# ── Step 4: anomaly detector ──────────────────────────────────────────────────

_REF = "RBI KYC MD 2025, Para 37 — Unusual transaction monitoring"


def detect_behavioral_anomaly(case: dict) -> dict:
    transactions = case.get("transactions", [])

    baseline = compute_baseline(transactions)
    if baseline is None:
        return {
            "flagged": False,
            "typology": "behavioral_anomaly",
            "confidence": 0.0,
            "evidence": {"reason": "insufficient_history"},
            "behavioral_score": 0.0,
            "regulatory_ref": _REF,
        }

    current = compute_current_window(transactions, days=30)
    if current["current_count"] == 0:
        return {
            "flagged": False,
            "typology": "behavioral_anomaly",
            "confidence": 0.0,
            "evidence": {"reason": "no_recent_transactions"},
            "behavioral_score": 0.0,
            "regulatory_ref": _REF,
        }

    amount_z = (
        abs(current["current_avg_amount_inr"] - baseline["avg_amount_inr"])
        / baseline["std_amount_inr"]
    )
    count_z = (
        abs(current["current_count"] - baseline["avg_monthly_txn_count"])
        / baseline["std_monthly_count"]
    )
    ch_shift = channel_distance(baseline["channel_distribution"], current["current_channel_dist"])
    new_cp_ratio = current["new_counterparty_ratio"]

    signals = []
    if amount_z >= 3.0:
        signals.append("amount_z_spike")
    if count_z >= 3.0:
        signals.append("count_z_spike")
    if ch_shift >= 0.5:
        signals.append("channel_shift")
    if new_cp_ratio >= 0.7:
        signals.append("new_counterparty_ratio")
    flagged = bool(signals)

    z_component = min(1.0, max(amount_z, count_z) / 6.0)
    behavioral_score = round(min(1.0, z_component * 0.5 + ch_shift * 0.25 + new_cp_ratio * 0.25), 4)

    return {
        "flagged": flagged,
        "typology": "behavioral_anomaly",
        "confidence": behavioral_score if flagged else 0.0,
        "evidence": {
            "amount_z": round(amount_z, 3),
            "count_z": round(count_z, 3),
            "channel_shift": round(ch_shift, 3),
            "new_counterparty_ratio": round(new_cp_ratio, 3),
            "signals": signals,
        },
        "behavioral_score": behavioral_score,
        "regulatory_ref": _REF,
    }
