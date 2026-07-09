"""
Phase 10B case-lifecycle persistence tests (api/store.py + lifecycle endpoints).

Runs against the local vigil Postgres (same as the RAG tests). Every row this
module creates uses a unique test prefix and is deleted afterwards.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.store import (
    _connect,
    get_stats,
    init_tables,
    record_review,
    save_investigation,
    save_triage,
)

client = TestClient(app)

_PFX = "t10b_" + uuid.uuid4().hex[:8]


def _case(suffix: str) -> dict:
    return {
        "case_id": f"{_PFX}_{suffix}",
        "customer": {"name": f"Test Customer {suffix}"},
        "transactions": [],
    }


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    init_tables()
    yield
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM vigil_reviews WHERE case_id LIKE %s", (_PFX + "%",))
        cur.execute("DELETE FROM vigil_cases WHERE case_id LIKE %s", (_PFX + "%",))


# ── 1. Table init is idempotent ───────────────────────────────────────────────


def test_init_tables_idempotent():
    init_tables()
    init_tables()  # second call must not raise


# ── 2. Triage persists and lists with the right status ────────────────────────


def test_triage_persists_and_lists():
    save_triage(_case("flag"), 0.82, True, "structuring")
    save_triage(_case("dism"), 0.11, False, None)

    r = client.get("/cases", params={"status": "flagged", "limit": 200})
    assert r.status_code == 200
    ids = {c["case_id"] for c in r.json()["cases"]}
    assert f"{_PFX}_flag" in ids
    assert f"{_PFX}_dism" not in ids


# ── 3. Investigation moves the case to in_review ──────────────────────────────


def test_investigation_sets_in_review():
    save_triage(_case("inv"), 0.9, True, "sanctions_hit")
    save_investigation(_case("inv"), "ESCALATE", 0.85, "sanctions_hit", "STR text")

    r = client.get(f"/cases/{_PFX}_inv")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "in_review"
    assert body["agent_decision"] == "ESCALATE"
    assert body["report"] == "STR text"


# ── 4. Review closes the case and writes the audit row ────────────────────────


def test_review_approve_escalate_files_str():
    save_investigation(_case("rev"), "ESCALATE", 0.9, "structuring", "STR")
    r = client.post(
        f"/cases/{_PFX}_rev/review",
        json={"reviewer": "R. Mehta", "action": "approve", "rationale": "Agree."},
    )
    assert r.status_code == 200
    assert r.json()["final_status"] == "str_filed"

    detail = client.get(f"/cases/{_PFX}_rev").json()
    assert detail["status"] == "str_filed"
    assert len(detail["reviews"]) == 1
    assert detail["reviews"][0]["reviewer"] == "R. Mehta"


def test_review_override_dismiss_files_str():
    save_investigation(_case("ovr"), "DISMISS", 0.7, "", "No STR")
    out = record_review(f"{_PFX}_ovr", "A. Rao", "override", "Disagree — escalate.")
    assert out["final_status"] == "str_filed"


# ── 5. Guard rails: unknown case, uninvestigated case, bad input ──────────────


def test_review_unknown_case_404():
    r = client.post(
        f"/cases/{_PFX}_missing/review",
        json={"reviewer": "X", "action": "approve"},
    )
    assert r.status_code == 404


def test_review_uninvestigated_400():
    save_triage(_case("raw"), 0.75, True, "structuring")  # triaged, never investigated
    r = client.post(
        f"/cases/{_PFX}_raw/review",
        json={"reviewer": "X", "action": "approve"},
    )
    assert r.status_code == 400


# ── 6. Stats shape and consistency ────────────────────────────────────────────


def test_stats_shape():
    stats = get_stats()
    for key in (
        "total_cases",
        "flagged",
        "auto_dismissed",
        "in_review",
        "str_filed",
        "dismissed",
        "reviews_recorded",
        "noise_reduction_pct",
        "review_approvals",
        "review_overrides",
        "agent_agreement_pct",
    ):
        assert key in stats
    buckets = (
        stats["flagged"]
        + stats["auto_dismissed"]
        + stats["in_review"]
        + stats["str_filed"]
        + stats["dismissed"]
    )
    assert buckets == stats["total_cases"]
    # The feedback loop must reconcile: approvals + overrides == reviews.
    assert stats["review_approvals"] + stats["review_overrides"] == stats["reviews_recorded"]

    r = client.get("/dashboard/stats")
    assert r.status_code == 200
    assert r.json()["total_cases"] >= 4  # the cases this module created
