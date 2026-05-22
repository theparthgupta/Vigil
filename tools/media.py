"""
Tool 3: Adverse media search.

Current implementation: DuckDuckGo Instant Answer API (free, no key required).
Falls back to an empty stub on network failure.

Interface is intentionally stable — swap _fetch_results() for Serper / Google
Custom Search / GDELT in Phase 6 without touching the caller.

Returns a plain JSON-serialisable dict.
"""

from __future__ import annotations

import httpx

_DDG_URL     = "https://api.duckduckgo.com/"
_TIMEOUT     = 6.0   # seconds — adversarial media search is best-effort


def search_adverse_media(name: str, max_results: int = 5) -> dict:
    """
    Search for adverse media mentions (fraud, AML, sanctions) for a given name.

    Returns:
        name_queried   str
        results        list[{title, snippet, url}]
        result_count   int
        is_stub        bool   True when no live results were returned
    """
    results = _fetch_results(name, max_results)
    return {
        "name_queried":  name,
        "results":       results,
        "result_count":  len(results),
        "is_stub":       len(results) == 0,
    }


# ── Provider ──────────────────────────────────────────────────────────────────

def _fetch_results(name: str, max_results: int) -> list[dict]:
    """
    Query DuckDuckGo's Instant Answer API with an AML-focused query.
    Returns [] on any network/parse error rather than raising.
    """
    params = {
        "q":              f"{name} money laundering fraud sanctions",
        "format":         "json",
        "no_html":        "1",
        "skip_disambig":  "1",
    }
    try:
        resp = httpx.get(_DDG_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    results: list[dict] = []

    # Abstract (Wikipedia-style summary)
    if data.get("Abstract") and data.get("AbstractURL"):
        results.append({
            "title":   data.get("Heading", name),
            "snippet": data["Abstract"][:300],
            "url":     data["AbstractURL"],
        })

    # Related topics
    for topic in data.get("RelatedTopics", []):
        if len(results) >= max_results:
            break
        # Topics are either flat dicts or nested {Topics: [...]}
        if "Text" in topic and "FirstURL" in topic:
            results.append({
                "title":   topic["Text"][:80],
                "snippet": topic["Text"],
                "url":     topic["FirstURL"],
            })

    return results[:max_results]
