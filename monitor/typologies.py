"""
Layer 1 of the Vigil monitor: a deterministic 10-typology rule engine.

Every detector is pure Python (no LLM). Each has the signature

    def detect_X(transactions: list[dict], customer: dict) -> dict

and returns:

    {
      "flagged": bool,
      "typology": str,
      "confidence": float,        # 0.0-1.0
      "evidence": dict,           # the specific numbers that triggered the flag
      "regulatory_ref": str,      # exact citation
    }

Transactions follow the Phase-1 schema: amount_inr (float), timestamp (ISO str),
direction ("credit"/"debit"), channel ("UPI"/"NEFT"/"RTGS"/"cash"/"IMPS"),
counterparty_name (str). Customer carries business_type and
stated_monthly_turnover_inr (alias: monthly_turnover_inr).
"""

from __future__ import annotations

import re
import statistics
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from tools.sanctions import check_sanctions

# ── Thresholds (INR) ──────────────────────────────────────────────────────────
_BAND_LOW = 800_000  # Rs.8 lakh
_BAND_HIGH = 999_999  # just under the Rs.10 lakh CTR threshold
_CTR = 1_000_000  # Rs.10 lakh
_PASS_CREDIT = 1_500_000  # Rs.15 lakh
_DORMANT_CREDIT = 500_000
_UPI_LOW = 50_000
_UPI_HIGH = 99_900


# ── Shared helpers ────────────────────────────────────────────────────────────


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _sorted(txns: list[dict]) -> list[dict]:
    return sorted(txns, key=lambda t: _dt(t["timestamp"]))


def _turnover(customer: dict) -> float:
    return float(
        customer.get("stated_monthly_turnover_inr") or customer.get("monthly_turnover_inr") or 0.0
    )


def _res(flagged: bool, typology: str, confidence: float, evidence: dict, ref: str) -> dict:
    return {
        "flagged": flagged,
        "typology": typology,
        "confidence": round(confidence, 3) if flagged else 0.0,
        "evidence": evidence,
        "regulatory_ref": ref,
    }


def _window(items: list[dict], days: int):
    """Yield, for each item as window start, the list of items within `days`."""
    its = _sorted(items)
    ts = [_dt(t["timestamp"]) for t in its]
    for i in range(len(its)):
        end = ts[i] + timedelta(days=days)
        yield [its[j] for j in range(len(its)) if ts[i] <= ts[j] <= end]


# ── 1. Structuring ────────────────────────────────────────────────────────────

# Phase 11C discriminative conditions (from SAML-D FP attribution):
_MIN_BAND_SHARE = 0.25  # near-threshold deposits must be >=25% of window credit volume
_MAX_CLUSTER_CV = 0.08  # amounts' pstdev must be <8% of their mean (uniformity)


def _clustered(amounts: list[float]) -> bool:
    mean = sum(amounts) / len(amounts)
    if mean <= 0:
        return False
    return statistics.pstdev(amounts) < _MAX_CLUSTER_CV * mean


def _band_share(grp: list[dict], all_credits: list[dict]) -> float:
    """Share of the account's credit volume (same 30-day window) in the group."""
    start = min(_dt(t["timestamp"]) for t in grp)
    end = start + timedelta(days=30)
    window_total = sum(t["amount_inr"] for t in all_credits if start <= _dt(t["timestamp"]) <= end)
    if window_total <= 0:
        return 0.0
    return sum(t["amount_inr"] for t in grp) / window_total


def detect_structuring(transactions: list[dict], customer: dict) -> dict:
    ref = "PMLA 2002, Section 12; PMLA Rules 2005, Rule 3(1)(A)"
    all_credits = [t for t in transactions if t["direction"] == "credit"]

    # Branch 1: >=3 cash deposits in the Rs.8L-9.99L band within any 30-day window.
    # Phase 11C: count alone is not discriminative (clean accounts routinely have
    # band-value traffic) — the deposits must also DOMINATE the account's credit
    # volume in that window (band_share) and be suspiciously uniform (clustering).
    cash_band = [
        t
        for t in transactions
        if t["direction"] == "credit"
        and t["channel"] == "cash"
        and _BAND_LOW <= t["amount_inr"] <= _BAND_HIGH
    ]
    for grp in _window(cash_band, 30):
        if len(grp) < 3:
            continue
        amounts = [t["amount_inr"] for t in grp]
        if not _clustered(amounts):
            continue
        if _band_share(grp, all_credits) < _MIN_BAND_SHARE:
            continue
        return _res(
            True,
            "structuring",
            0.85,
            {
                "deposit_amounts": amounts,
                "dates": [t["timestamp"][:10] for t in grp],
                "channel_count": len({t["channel"] for t in grp}),
                "band_share": round(_band_share(grp, all_credits), 3),
            },
            ref,
        )

    # Branch 2: total deposits > Rs.10L across >=2 channels within any 30-day window.
    # Phase 11C: ">10L over two channels" alone fires on nearly every active
    # account (measured on SAML-D: this branch alone put 91% of clean accounts
    # over the triage line). Splitting-to-evade looks like SEVERAL sub-threshold
    # credits of suspiciously similar size — so require >=3 credits, each below
    # the CTR, with clustered amounts, alongside the original total/channel test.
    credits = [t for t in transactions if t["direction"] == "credit"]
    for grp in _window(credits, 30):
        total = sum(t["amount_inr"] for t in grp)
        channels = {t["channel"] for t in grp}
        if total <= _CTR or len(channels) < 2:
            continue
        sub_ctr = [t for t in grp if t["amount_inr"] < _CTR]
        if len(sub_ctr) < 3:
            continue
        amounts = [t["amount_inr"] for t in sub_ctr]
        if not _clustered(amounts):
            continue
        return _res(
            True,
            "structuring",
            0.85,
            {
                "deposit_amounts": amounts,
                "dates": [t["timestamp"][:10] for t in sub_ctr],
                "channel_count": len(channels),
            },
            ref,
        )

    return _res(
        False, "structuring", 0.0, {"deposit_amounts": [], "dates": [], "channel_count": 0}, ref
    )


# ── 2. Rapid pass-through ─────────────────────────────────────────────────────


def detect_rapid_passthrough(transactions: list[dict], customer: dict) -> dict:
    ref = "FATF Typologies — Layering via rapid fund movement"
    txns = _sorted(transactions)
    seen: set[str] = set()

    for i, txn in enumerate(txns):
        if txn["direction"] != "credit" or txn["amount_inr"] < _PASS_CREDIT:
            seen.add(txn["counterparty_name"])
            continue

        credit = txn["amount_inr"]
        prior = frozenset(seen)
        end = _dt(txn["timestamp"]) + timedelta(hours=72)
        new_debits = [
            s
            for s in txns[i + 1 :]
            if s["direction"] == "debit"
            and _dt(s["timestamp"]) <= end
            and s["counterparty_name"] not in prior
        ]
        new_payees = sorted({s["counterparty_name"] for s in new_debits})
        if len(new_payees) >= 3:
            ratio = sum(s["amount_inr"] for s in new_debits) / credit
            if ratio >= 0.70:
                return _res(
                    True,
                    "rapid_passthrough",
                    0.85,
                    {
                        "trigger_credit_inr": round(credit, 2),
                        "debit_count": len(new_debits),
                        "passthrough_ratio": round(ratio, 3),
                        "new_payees": new_payees,
                    },
                    ref,
                )
        seen.add(txn["counterparty_name"])

    return _res(
        False,
        "rapid_passthrough",
        0.0,
        {
            "trigger_credit_inr": None,
            "debit_count": 0,
            "passthrough_ratio": None,
            "new_payees": [],
        },
        ref,
    )


# ── 3. Sanctions hit ──────────────────────────────────────────────────────────


def detect_sanctions_hit(transactions: list[dict], customer: dict) -> dict:
    ref = "PMLA 2002, Section 12A; UAPA 1967"
    names = sorted({t["counterparty_name"] for t in transactions})
    hits = [r for n in names if (r := check_sanctions(n))["is_match"]]
    return _res(bool(hits), "sanctions_hit", 1.0, {"hits": hits, "names_checked": len(names)}, ref)


# ── 4. Round-trip ─────────────────────────────────────────────────────────────


def detect_round_trip(transactions: list[dict], customer: dict) -> dict:
    ref = "APG Typologies 2024 — Circular transactions / Round-tripping"
    txns = _sorted(transactions)

    for i, d in enumerate(txns):
        if d["direction"] != "debit":
            continue
        d_amt, d_t = d["amount_inr"], _dt(d["timestamp"])
        for c in txns[i + 1 :]:
            days = (_dt(c["timestamp"]) - d_t).days
            if days > 14:
                break  # sorted: every later credit is even further out
            if c["direction"] != "credit":
                continue
            same = (
                c["counterparty_name"] == d["counterparty_name"]
                or SequenceMatcher(
                    None, d["counterparty_name"].lower(), c["counterparty_name"].lower()
                ).ratio()
                >= 0.85
            )
            if same and d_amt > 0 and abs(c["amount_inr"] - d_amt) / d_amt <= 0.10:
                return _res(
                    True,
                    "round_trip",
                    0.75,
                    {
                        "counterparty": d["counterparty_name"],
                        "debit_amount": round(d_amt, 2),
                        "credit_amount": round(c["amount_inr"], 2),
                        "days_elapsed": days,
                    },
                    ref,
                )

    return _res(
        False,
        "round_trip",
        0.0,
        {
            "counterparty": None,
            "debit_amount": None,
            "credit_amount": None,
            "days_elapsed": None,
        },
        ref,
    )


# ── 5. Velocity spike ─────────────────────────────────────────────────────────


def detect_velocity_spike(transactions: list[dict], customer: dict) -> dict:
    ref = "RBI KYC MD 2025, Para 37 — Enhanced monitoring triggers"
    if len(transactions) < 20:
        return _res(False, "velocity_spike", 0.0, {"reason": "insufficient_history"}, ref)

    ts = [_dt(t["timestamp"]) for t in transactions]
    recent = max(ts)
    last_7d = sum(1 for t in ts if t > recent - timedelta(days=7))
    count_30d = sum(1 for t in ts if t > recent - timedelta(days=30))
    baseline = round(count_30d * 7 / 30, 3)  # expected 7-day count
    ratio = round(last_7d / baseline, 3) if baseline > 0 else 0.0
    flagged = baseline > 0 and ratio > 3.0

    return _res(
        flagged,
        "velocity_spike",
        0.65,
        {
            "last_7d_count": last_7d,
            "baseline_30d_avg": baseline,
            "spike_ratio": ratio,
        },
        ref,
    )


# ── 6. Dormant reactivation ───────────────────────────────────────────────────


def detect_dormant_reactivation(transactions: list[dict], customer: dict) -> dict:
    ref = "RBI KYC MD 2025, Para 37(b) — Dormant account monitoring"
    txns = _sorted(transactions)
    ts = [_dt(t["timestamp"]) for t in txns]

    for i in range(1, len(txns)):
        gap = (ts[i] - ts[i - 1]).days
        if (
            gap >= 90
            and txns[i]["direction"] == "credit"
            and txns[i]["amount_inr"] >= _DORMANT_CREDIT
        ):
            window_end = ts[i] + timedelta(days=7)
            debits = [
                txns[j]
                for j in range(i + 1, len(txns))
                if ts[j] <= window_end and txns[j]["direction"] == "debit"
            ]
            if len(debits) >= 2:
                return _res(
                    True,
                    "dormant_reactivation",
                    0.65,
                    {
                        "dormancy_days": gap,
                        "reactivation_credit_inr": round(txns[i]["amount_inr"], 2),
                        "rapid_debit_count": len(debits),
                    },
                    ref,
                )

    return _res(
        False,
        "dormant_reactivation",
        0.0,
        {
            "dormancy_days": 0,
            "reactivation_credit_inr": None,
            "rapid_debit_count": 0,
        },
        ref,
    )


# ── 7. Smurfing network ───────────────────────────────────────────────────────


def detect_smurfing_network(transactions: list[dict], customer: dict) -> dict:
    ref = "APG Typologies 2024 — Multi-source structuring networks"
    band = [
        t
        for t in transactions
        if t["direction"] == "credit" and _BAND_LOW <= t["amount_inr"] <= _BAND_HIGH
    ]
    for grp in _window(band, 30):
        senders = {t["counterparty_name"] for t in grp}
        if len(senders) >= 3:
            amounts = [t["amount_inr"] for t in grp]
            return _res(
                True,
                "smurfing_network",
                0.80,
                {
                    "sender_names": sorted(senders),
                    "individual_amounts": amounts,
                    "combined_total_inr": round(sum(amounts), 2),
                    "window_days": 30,
                },
                ref,
            )

    return _res(
        False,
        "smurfing_network",
        0.0,
        {
            "sender_names": [],
            "individual_amounts": [],
            "combined_total_inr": 0.0,
            "window_days": 30,
        },
        ref,
    )


# ── 8. High-risk sector volume spike ──────────────────────────────────────────


def detect_high_risk_sector_spike(transactions: list[dict], customer: dict) -> dict:
    ref = "RBI KYC MD 2025, Para 45 — High-risk sector enhanced monitoring"
    btype = customer.get("business_type")
    turnover = _turnover(customer)

    if btype not in ("jewelry", "real_estate", "logistics") or turnover <= 0:
        return _res(
            False,
            "high_risk_sector_spike",
            0.0,
            {
                "stated_turnover_inr": turnover,
                "actual_volume_inr": 0.0,
                "ratio": 0.0,
                "business_type": btype,
            },
            ref,
        )

    by_month: dict[tuple, float] = {}
    for t in transactions:
        d = _dt(t["timestamp"])
        by_month[(d.year, d.month)] = by_month.get((d.year, d.month), 0.0) + t["amount_inr"]

    actual = max(by_month.values()) if by_month else 0.0
    ratio = actual / turnover if turnover else 0.0
    flagged = ratio > 2.0

    return _res(
        flagged,
        "high_risk_sector_spike",
        0.60,
        {
            "stated_turnover_inr": round(turnover, 2),
            "actual_volume_inr": round(actual, 2),
            "ratio": round(ratio, 3),
            "business_type": btype,
        },
        ref,
    )


# ── 9. UPI micro-structuring ──────────────────────────────────────────────────


def detect_upi_micro_structuring(transactions: list[dict], customer: dict) -> dict:
    ref = "RBI KYC MD 2025, Para 53 — Digital payment channel monitoring"
    band = [
        t
        for t in transactions
        if t["direction"] == "credit"
        and t["channel"] == "UPI"
        and _UPI_LOW <= t["amount_inr"] <= _UPI_HIGH
    ]
    for grp in _window(band, 7):
        senders = {t["counterparty_name"] for t in grp}
        if len(grp) >= 15 and len(senders) >= 8:
            return _res(
                True,
                "upi_micro_structuring",
                0.75,
                {
                    "upi_credit_count": len(grp),
                    "unique_sender_count": len(senders),
                    "total_amount_inr": round(sum(t["amount_inr"] for t in grp), 2),
                    "window_days": 7,
                },
                ref,
            )

    return _res(
        False,
        "upi_micro_structuring",
        0.0,
        {
            "upi_credit_count": 0,
            "unique_sender_count": 0,
            "total_amount_inr": 0.0,
            "window_days": 7,
        },
        ref,
    )


# ── 10. Geographic anomaly ────────────────────────────────────────────────────

_STATE_MARKERS = {
    "kerala": "Kerala",
    "tamil": "Tamil Nadu",
    "chennai": "Tamil Nadu",
    "bengal": "West Bengal",
    "kolkata": "West Bengal",
    "punjab": "Punjab",
    "rajasthan": "Rajasthan",
    "gujarat": "Gujarat",
    "ahmedabad": "Gujarat",
    "marathi": "Maharashtra",
    "mumbai": "Maharashtra",
    "andhra": "Andhra Pradesh",
    "telangana": "Telangana",
    "hyderabad": "Telangana",
    "karnataka": "Karnataka",
    "bangalore": "Karnataka",
    "odisha": "Odisha",
    "bihar": "Bihar",
    "up": "Uttar Pradesh",
    "mp": "Madhya Pradesh",
    "delhi": "Delhi",
}
_MARKER_RE = {m: re.compile(rf"\b{re.escape(m)}\b", re.I) for m in _STATE_MARKERS}


def _states_in(name: str) -> set[str]:
    return {state for m, state in _STATE_MARKERS.items() if _MARKER_RE[m].search(name)}


def detect_geographic_anomaly(transactions: list[dict], customer: dict) -> dict:
    ref = "FATF — Geographic dispersal as layering indicator"
    btype = customer.get("business_type")
    if btype not in ("retail", "restaurant", "individual"):
        return _res(False, "geographic_anomaly", 0.0, {"reason": "sector_not_applicable"}, ref)

    tagged = [(t, _states_in(t["counterparty_name"])) for t in transactions]
    if not any(states for _, states in tagged):
        return _res(
            False, "geographic_anomaly", 0.0, {"reason": "state_inference_unavailable"}, ref
        )

    txns = _sorted([t for t, states in tagged if states])
    ts = [_dt(t["timestamp"]) for t in txns]
    for i in range(len(txns)):
        end = ts[i] + timedelta(days=7)
        states: set[str] = set()
        for j in range(len(txns)):
            if ts[i] <= ts[j] <= end:
                states |= _states_in(txns[j]["counterparty_name"])
        if len(states) >= 4:
            return _res(
                True,
                "geographic_anomaly",
                0.55,
                {
                    "states_detected": sorted(states),
                    "state_count": len(states),
                    "window_days": 7,
                },
                ref,
            )

    return _res(
        False,
        "geographic_anomaly",
        0.0,
        {
            "states_detected": [],
            "state_count": 0,
            "window_days": 7,
        },
        ref,
    )
