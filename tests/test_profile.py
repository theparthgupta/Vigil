"""
Tool 4 tests: customer risk profile summariser.

Tests use both synthetic fixtures and actual train-split cases.
"""

from tools.profile import summarize_profile

_REQUIRED_KEYS = {
    "customer_id",
    "name",
    "business_type",
    "stated_monthly_turnover_inr",
    "account_age_days",
    "prior_flags",
    "risk_factors",
    "risk_level",
    "summary",
}
_VALID_LEVELS = {"low", "medium", "high"}


# ── Synthetic fixtures ────────────────────────────────────────────────────────

_JEWELRY_HIGH_RISK = {
    "id": "test_jewelry_001",
    "name": "Gold Palace Jewellers",
    "business_type": "jewelry",
    "account_open_date": "2025-06-01T00:00:00",  # < 1 year old
    "stated_monthly_turnover_inr": 5_000_000.0,
    "prior_flags": 2,
}

_RETAIL_LOW_RISK = {
    "id": "test_retail_001",
    "name": "Sharma General Store",
    "business_type": "retail",
    "account_open_date": "2020-01-01T00:00:00",  # 5+ years old
    "stated_monthly_turnover_inr": 500_000.0,
    "prior_flags": 0,
}


def test_high_risk_profile_scores_high():
    result = summarize_profile(_JEWELRY_HIGH_RISK)
    assert result["risk_level"] == "high", (
        f"Expected 'high', got '{result['risk_level']}'. risk_factors={result['risk_factors']}"
    )


def test_high_risk_profile_has_multiple_risk_factors():
    result = summarize_profile(_JEWELRY_HIGH_RISK)
    assert len(result["risk_factors"]) >= 2


def test_low_risk_retail_not_high():
    result = summarize_profile(_RETAIL_LOW_RISK)
    assert result["risk_level"] in {"low", "medium"}
    assert result["prior_flags"] == 0


def test_return_structure_is_complete():
    result = summarize_profile(_RETAIL_LOW_RISK)
    assert _REQUIRED_KEYS <= result.keys()


def test_risk_level_is_valid_enum():
    result = summarize_profile(_JEWELRY_HIGH_RISK)
    assert result["risk_level"] in _VALID_LEVELS


def test_summary_is_non_empty_string():
    result = summarize_profile(_RETAIL_LOW_RISK)
    assert isinstance(result["summary"], str) and len(result["summary"]) > 20


# ── Train-case tests ──────────────────────────────────────────────────────────


def test_profile_from_structuring_case(cases_by_typology):
    case = cases_by_typology["structuring"][0]
    result = summarize_profile(case["customer"])
    assert result["customer_id"] == case["customer"]["id"]
    assert result["risk_level"] in _VALID_LEVELS
    assert result["stated_monthly_turnover_inr"] > 0


def test_profile_from_second_structuring_case(cases_by_typology):
    case = cases_by_typology["structuring"][1]
    result = summarize_profile(case["customer"])
    assert _REQUIRED_KEYS <= result.keys()
    assert result["risk_level"] in _VALID_LEVELS


def test_profile_from_clean_case(cases_by_typology):
    case = cases_by_typology["clean"][0]
    result = summarize_profile(case["customer"])
    assert result["customer_id"] == case["customer"]["id"]
    assert isinstance(result["risk_factors"], list)


def test_profile_from_second_clean_case(cases_by_typology):
    case = cases_by_typology["clean"][1]
    result = summarize_profile(case["customer"])
    assert result["risk_level"] in _VALID_LEVELS
