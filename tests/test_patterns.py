"""
Tool 2 tests: deterministic transaction pattern analyser.

Tests verify that the structuring and rapid-passthrough detectors flag the
correct train cases and do NOT fire on clean cases.
"""

import pytest

from tools.patterns import analyze_patterns


# ── Structuring indicator ─────────────────────────────────────────────────────

def test_structuring_case_is_flagged(cases_by_typology):
    case = cases_by_typology["structuring"][0]
    result = analyze_patterns(case["transactions"])
    assert result["structuring_indicator"]["flagged"] is True, (
        f"Expected structuring flag in {case['case_id']}. "
        f"near_threshold_cash_count={result['structuring_indicator']['near_threshold_cash_count']}"
    )


def test_structuring_case_near_threshold_count_ge_3(cases_by_typology):
    case = cases_by_typology["structuring"][0]
    result = analyze_patterns(case["transactions"])
    assert result["structuring_indicator"]["near_threshold_cash_count"] >= 3


def test_second_structuring_case_flagged(cases_by_typology):
    case = cases_by_typology["structuring"][1]
    result = analyze_patterns(case["transactions"])
    assert result["structuring_indicator"]["flagged"] is True


# ── Rapid pass-through indicator ──────────────────────────────────────────────

def test_rapid_passthrough_case_is_flagged(cases_by_typology):
    case = cases_by_typology["rapid_passthrough"][0]
    result = analyze_patterns(case["transactions"])
    rp = result["rapid_passthrough_indicator"]
    assert rp["flagged"] is True, (
        f"Expected passthrough flag in {case['case_id']}. "
        f"trigger_credit={rp['trigger_credit_inr']}, "
        f"debit_count={rp['debit_count_within_72h']}, "
        f"ratio={rp['passthrough_ratio']}"
    )


def test_rapid_passthrough_ratio_ge_80_percent(cases_by_typology):
    case = cases_by_typology["rapid_passthrough"][0]
    result = analyze_patterns(case["transactions"])
    ratio = result["rapid_passthrough_indicator"]["passthrough_ratio"]
    assert ratio is not None and ratio >= 0.80


def test_second_passthrough_case_flagged(cases_by_typology):
    case = cases_by_typology["rapid_passthrough"][1]
    result = analyze_patterns(case["transactions"])
    assert result["rapid_passthrough_indicator"]["flagged"] is True


# ── Clean cases must NOT fire ─────────────────────────────────────────────────

def test_clean_case_no_structuring_flag(cases_by_typology):
    case = cases_by_typology["clean"][0]
    result = analyze_patterns(case["transactions"])
    assert result["structuring_indicator"]["flagged"] is False


def test_clean_case_no_passthrough_flag(cases_by_typology):
    case = cases_by_typology["clean"][0]
    result = analyze_patterns(case["transactions"])
    assert result["rapid_passthrough_indicator"]["flagged"] is False


def test_second_clean_case_clean(cases_by_typology):
    case = cases_by_typology["clean"][1]
    result = analyze_patterns(case["transactions"])
    assert result["structuring_indicator"]["flagged"] is False
    assert result["rapid_passthrough_indicator"]["flagged"] is False


# ── Basic stats sanity ────────────────────────────────────────────────────────

def test_basic_stats_are_populated(cases_by_typology):
    case = cases_by_typology["structuring"][0]
    result = analyze_patterns(case["transactions"])
    assert result["total_transactions"] == len(case["transactions"])
    assert result["avg_amount_inr"] > 0
    assert result["median_amount_inr"] > 0
    assert result["unique_counterparties"] > 0
    assert 0.0 <= result["counterparty_diversity_ratio"] <= 1.0
    assert result["cash_credit_total_inr"] > 0


def test_empty_transactions_returns_zeros():
    result = analyze_patterns([])
    assert result["total_transactions"] == 0
    assert result["structuring_indicator"]["flagged"] is False
    assert result["rapid_passthrough_indicator"]["flagged"] is False
