"""
Tool 3 tests: adverse media search.

The DuckDuckGo backend is best-effort (network may be unavailable in CI).
Tests only assert that the return structure is stable — not the content —
so they pass regardless of network state.
"""

from tools.media import search_adverse_media

_REQUIRED_KEYS = {"name_queried", "results", "result_count", "is_stub"}


def test_return_structure_is_complete():
    result = search_adverse_media("Dawood Merchant")
    assert _REQUIRED_KEYS <= result.keys()


def test_name_is_preserved():
    name = "Omar Sheikh Qureshi"
    result = search_adverse_media(name)
    assert result["name_queried"] == name


def test_results_is_a_list():
    result = search_adverse_media("Viktor Petrov")
    assert isinstance(result["results"], list)


def test_result_count_matches_list_length():
    result = search_adverse_media("Khalid Al-Rashidi")
    assert result["result_count"] == len(result["results"])


def test_each_result_has_required_fields():
    result = search_adverse_media("Dawood Merchant")
    for item in result["results"]:
        assert "title" in item
        assert "snippet" in item
        assert "url" in item


def test_clean_name_returns_stable_structure():
    result = search_adverse_media("Rajesh Kumar Sharma")
    assert _REQUIRED_KEYS <= result.keys()
    assert isinstance(result["results"], list)
