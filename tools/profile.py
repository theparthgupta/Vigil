"""
Tool 4: Customer risk profile summariser (deterministic).

Extracts and structures risk-relevant facts from a CustomerProfile dict.
No LLM — this feeds raw, structured evidence into the LangGraph Reasoner,
which does the synthesis and final decision.

Regulatory anchors:
  - RBI KYC Master Directions 2016, Chapter IV: risk categorisation of customers
  - High-risk business types: jewelry, real_estate, logistics (cash-intensive or
    high-value goods susceptible to trade-based money laundering)
  - PMLA 2002, Section 11A: enhanced due diligence for high-risk categories
"""

from __future__ import annotations

from datetime import datetime

# RBI KYC Master Directions 2016 — Table of inherently high-risk business types
_HIGH_RISK_BTYPES   = {"jewelry", "real_estate", "logistics"}
_MEDIUM_RISK_BTYPES = {"hospitality", "textile", "sme"}

_AGE_HIGH_DAYS   = 180   # < 6 months → elevated monitoring (new customer risk)
_AGE_MEDIUM_DAYS = 365   # < 1 year   → moderate monitoring


def summarize_profile(customer: dict) -> dict:
    """
    Return a structured risk summary for a CustomerProfile dict.

    Returns:
        customer_id                  str
        name                         str
        business_type                str
        stated_monthly_turnover_inr  float
        account_age_days             int
        prior_flags                  int
        risk_factors                 list[str]   — human-readable, citable
        risk_level                   "low" | "medium" | "high"
        summary                      str         — single-paragraph for the Reasoner
    """
    btype         = customer["business_type"]
    prior_flags   = customer["prior_flags"]
    turnover      = customer["stated_monthly_turnover_inr"]
    opened        = datetime.fromisoformat(customer["account_open_date"])
    age_days      = (datetime.now() - opened).days

    risk_factors: list[str] = []

    if btype in _HIGH_RISK_BTYPES:
        risk_factors.append(
            f"High-risk business sector: {btype} "
            "(RBI KYC Master Directions 2016 — cash-intensive or high-value goods)"
        )
    elif btype in _MEDIUM_RISK_BTYPES:
        risk_factors.append(f"Medium-risk business sector: {btype}")

    if age_days < _AGE_HIGH_DAYS:
        risk_factors.append(
            f"New account: {age_days} days old "
            "(< 6 months — elevated monitoring required per RBI KYC s.16)"
        )
    elif age_days < _AGE_MEDIUM_DAYS:
        risk_factors.append(f"Relatively new account: {age_days} days old (< 1 year)")

    if prior_flags >= 2:
        risk_factors.append(
            f"{prior_flags} prior flags — enhanced due diligence mandatory "
            "(PMLA 2002, Section 11A)"
        )
    elif prior_flags == 1:
        risk_factors.append(f"1 prior flag on record")

    risk_level = _risk_level(btype, age_days, prior_flags)

    summary = (
        f"{customer['name']} is a {btype} entity, "
        f"account open for {age_days} days, "
        f"stated monthly turnover Rs.{turnover/1e5:.1f}L, "
        f"{prior_flags} prior flag(s). "
        f"Risk assessed as {risk_level.upper()}."
    )
    if risk_factors:
        summary += " Factors: " + "; ".join(risk_factors) + "."

    return {
        "customer_id":                 customer["id"],
        "name":                        customer["name"],
        "business_type":               btype,
        "stated_monthly_turnover_inr": turnover,
        "account_age_days":            age_days,
        "prior_flags":                 prior_flags,
        "risk_factors":                risk_factors,
        "risk_level":                  risk_level,
        "summary":                     summary,
    }


def _risk_level(btype: str, age_days: int, prior_flags: int) -> str:
    score = 0
    if btype in _HIGH_RISK_BTYPES:
        score += 2
    elif btype in _MEDIUM_RISK_BTYPES:
        score += 1
    if age_days < _AGE_HIGH_DAYS:
        score += 2
    elif age_days < _AGE_MEDIUM_DAYS:
        score += 1
    score += min(prior_flags, 2)   # cap at 2 so a single field can't overwhelm

    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"
