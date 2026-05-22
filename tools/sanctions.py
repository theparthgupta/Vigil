"""
Tool 1: Sanctions / PEP name screening.

Priority:
  1. OpenSanctions /match API  (if OPENSANCTIONS_API_KEY is set in .env)
  2. Local hardcoded fake-sanctions list (offline / synthetic-data mode)

Returns a plain dict so the caller can put it straight into LangGraph state.
"""

from __future__ import annotations

import os
from difflib import SequenceMatcher

import httpx
from dotenv import load_dotenv

load_dotenv()

_OPENSANCTIONS_URL = "https://api.opensanctions.org/match/default"
_MATCH_THRESHOLD = 0.6      # scores at or above this = positive hit
_REQUEST_TIMEOUT = 10.0     # seconds

# Mirrors SANCTIONED_NAMES in data/generator.py — used when API key is absent
_LOCAL_LIST: list[str] = [
    "Dawood Merchant",
    "Khalid Al-Rashidi",
    "Viktor Petrov",
    "Mehmet Yildirim Ozcan",
    "Farooq Ibrahim Siddiqui",
    "Sergei Volkov",
    "Hassan Al-Farouqi",
    "Chen Wei Guang",
    "Mohammad Aziz Karimov",
    "Yusuf Bello Adeyemi",
    "Reza Tehrani Moghaddam",
    "Abdul Majid Haqqani",
    "Nikolai Gromov",
    "Tariq Mahmood Chaudhry",
    "Ali Hassan Mousa",
    "Dmitri Sorokin",
    "Bashir Ahmad Zahed",
    "Liang Xiaoming",
    "Omar Sheikh Qureshi",
    "Pavlo Kovalenko",
]


def check_sanctions(name: str) -> dict:
    """
    Screen a single name against sanctions / PEP lists.

    Returns:
        name_queried       str
        is_match           bool
        match_score        float   0.0 – 1.0
        matched_entity     str | None
        sanctions_programs list[str]
        risk_tags          list[str]
        source             "opensanctions_api" | "local_list"
    """
    api_key = os.getenv("OPENSANCTIONS_API_KEY", "").strip()
    if api_key:
        return _via_api(name, api_key)
    return _via_local_list(name)


# ── OpenSanctions REST API ────────────────────────────────────────────────────

def _via_api(name: str, api_key: str) -> dict:
    payload = {
        "queries": {
            "q0": {"schema": "Thing", "properties": {"name": [name]}}
        }
    }
    headers = {
        "Authorization": f"ApiKey {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = httpx.post(
            _OPENSANCTIONS_URL, json=payload, headers=headers,
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("responses", {}).get("q0", {}).get("results", [])
    except httpx.HTTPError as exc:
        return {**_no_match(name, "opensanctions_api"), "error": str(exc)}

    if not results or results[0].get("score", 0.0) < _MATCH_THRESHOLD:
        return _no_match(name, "opensanctions_api")

    top = results[0]
    props = top.get("properties", {})
    return {
        "name_queried": name,
        "is_match": True,
        "match_score": round(top["score"], 3),
        "matched_entity": top.get("caption"),
        "sanctions_programs": top.get("datasets", []),
        "risk_tags": props.get("topics", []),
        "source": "opensanctions_api",
    }


# ── Local fuzzy fallback ──────────────────────────────────────────────────────

def _via_local_list(name: str) -> dict:
    name_lower = name.lower().strip()
    best_score, best_match = 0.0, None
    for entry in _LOCAL_LIST:
        score = SequenceMatcher(None, name_lower, entry.lower()).ratio()
        if score > best_score:
            best_score, best_match = score, entry

    if best_score >= _MATCH_THRESHOLD:
        return {
            "name_queried": name,
            "is_match": True,
            "match_score": round(best_score, 3),
            "matched_entity": best_match,
            "sanctions_programs": ["local_test_list"],
            "risk_tags": ["sanction"],
            "source": "local_list",
        }
    return _no_match(name, "local_list")


def _no_match(name: str, source: str) -> dict:
    return {
        "name_queried": name,
        "is_match": False,
        "match_score": 0.0,
        "matched_entity": None,
        "sanctions_programs": [],
        "risk_tags": [],
        "source": source,
    }
