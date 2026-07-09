"""
Tool 1 tests: sanctions / PEP screening.

All tests run against the local fuzzy-match list — `check_sanctions` defaults to
the local source (use_api=False), so these are deterministic and never touch the
network, regardless of whether OPENSANCTIONS_API_KEY is set.
Two real train cases are used: one sanctions_hit, one clean.
"""

from tools.sanctions import check_sanctions


# ── Direct name tests ─────────────────────────────────────────────────────────


def test_exact_sanctioned_name_is_flagged():
    result = check_sanctions("Ali Hassan Mousa")
    assert result["is_match"] is True
    assert result["match_score"] >= 0.9  # near-exact match
    assert result["matched_entity"] == "Ali Hassan Mousa"
    assert result["source"] == "local_list"


def test_clean_indian_name_is_not_flagged():
    result = check_sanctions("Rajesh Kumar Sharma")
    assert result["is_match"] is False
    assert result["match_score"] < _MATCH_THRESHOLD
    assert result["matched_entity"] is None


def test_partial_name_match_above_threshold():
    # "Khalid Al-Rashidi" shortened — should still score >= 0.6
    result = check_sanctions("Khalid Rashidi")
    assert result["is_match"] is True


def test_return_structure_is_complete():
    result = check_sanctions("Test Name")
    required = {
        "name_queried",
        "is_match",
        "match_score",
        "matched_entity",
        "sanctions_programs",
        "risk_tags",
        "source",
    }
    assert required <= result.keys()


# ── Train-case tests ──────────────────────────────────────────────────────────


def test_sanctions_hit_case_has_at_least_one_match(cases_by_typology):
    """Every sanctions_hit case must have ≥1 counterparty that triggers a hit."""
    case = cases_by_typology["sanctions_hit"][0]
    counterparties = {t["counterparty_name"] for t in case["transactions"]}
    hits = [check_sanctions(cp) for cp in counterparties if check_sanctions(cp)["is_match"]]
    assert len(hits) >= 1, (
        f"Expected ≥1 sanctions hit in {case['case_id']}. Counterparties: {counterparties}"
    )


def test_second_sanctions_hit_case_also_flags(cases_by_typology):
    case = cases_by_typology["sanctions_hit"][1]
    counterparties = {t["counterparty_name"] for t in case["transactions"]}
    assert any(check_sanctions(cp)["is_match"] for cp in counterparties)


def test_clean_case_produces_no_hits(cases_by_typology):
    """Clean cases must not trigger any sanctions flag."""
    case = cases_by_typology["clean"][0]
    counterparties = {t["counterparty_name"] for t in case["transactions"]}
    assert not any(check_sanctions(cp)["is_match"] for cp in counterparties), (
        f"Unexpected sanctions hit in clean case {case['case_id']}"
    )


def test_second_clean_case_also_clean(cases_by_typology):
    case = cases_by_typology["clean"][1]
    counterparties = {t["counterparty_name"] for t in case["transactions"]}
    assert not any(check_sanctions(cp)["is_match"] for cp in counterparties)


# Inline threshold so the assertion message is readable
_MATCH_THRESHOLD = 0.6
