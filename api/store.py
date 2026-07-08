"""
Case-lifecycle persistence for Vigil (Phase 10B).

Every triaged case, completed investigation, and reviewer action is written to
Postgres (same DATABASE_URL as the RAG store) so nothing vanishes on refresh —
the audit trail PMLA record-keeping expects. Plain psycopg2, same style as
rag/retrieve_pg.py, no ORM.

Status lifecycle:
    flagged | auto_dismissed      (monitor triage)
        -> in_review              (agent investigation completed)
            -> str_filed | dismissed   (reviewer action, logged in vigil_reviews)
"""

from __future__ import annotations

import json
import os
import threading

import psycopg2
from dotenv import load_dotenv

load_dotenv()

VALID_REVIEW_ACTIONS = ("approve", "override")

_init_done = False
_init_lock = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS vigil_cases (
    case_id          TEXT PRIMARY KEY,
    customer_name    TEXT NOT NULL,
    payload          JSONB NOT NULL,
    risk_score       DOUBLE PRECISION,
    top_typology     TEXT,
    status           TEXT NOT NULL,
    agent_decision   TEXT,
    agent_confidence DOUBLE PRECISION,
    report           TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS vigil_reviews (
    id           SERIAL PRIMARY KEY,
    case_id      TEXT NOT NULL REFERENCES vigil_cases(case_id),
    reviewer     TEXT NOT NULL,
    action       TEXT NOT NULL,
    final_status TEXT NOT NULL,
    rationale    TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Phase 11: per-investigation LLM cost (tokens counted by callback, ₹ math in Python).
ALTER TABLE vigil_cases ADD COLUMN IF NOT EXISTS tokens_used BIGINT;
ALTER TABLE vigil_cases ADD COLUMN IF NOT EXISTS cost_inr DOUBLE PRECISION;
"""


def _connect():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def init_tables() -> None:
    """Create the case/review tables if absent. Idempotent, once per process."""
    global _init_done
    if _init_done:
        return
    with _init_lock:
        if _init_done:
            return
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(_DDL)
        _init_done = True


def save_triage(
    case: dict,
    risk_score: float,
    above_threshold: bool,
    top_typology: str | None,
) -> None:
    """Upsert a triaged case. Never downgrades a case a human already acted on."""
    init_tables()
    status = "flagged" if above_threshold else "auto_dismissed"
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO vigil_cases (case_id, customer_name, payload, risk_score,
                                     top_typology, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (case_id) DO UPDATE SET
                payload      = EXCLUDED.payload,
                risk_score   = EXCLUDED.risk_score,
                top_typology = EXCLUDED.top_typology,
                status = CASE WHEN vigil_cases.status IN ('in_review','str_filed','dismissed')
                              THEN vigil_cases.status ELSE EXCLUDED.status END,
                updated_at   = now()
            """,
            (
                case.get("case_id", "unknown"),
                case.get("customer", {}).get("name", "unknown"),
                json.dumps(case),
                risk_score,
                top_typology,
                status,
            ),
        )


def save_investigation(
    case: dict,
    decision: str,
    confidence: float,
    typology: str,
    report: str,
    tokens_used: int | None = None,
    cost_inr: float | None = None,
) -> None:
    """Record a completed agent investigation; the case moves to in_review."""
    init_tables()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO vigil_cases (case_id, customer_name, payload, top_typology,
                                     status, agent_decision, agent_confidence, report,
                                     tokens_used, cost_inr)
            VALUES (%s, %s, %s, %s, 'in_review', %s, %s, %s, %s, %s)
            ON CONFLICT (case_id) DO UPDATE SET
                top_typology     = COALESCE(NULLIF(EXCLUDED.top_typology, ''),
                                            vigil_cases.top_typology),
                status           = 'in_review',
                agent_decision   = EXCLUDED.agent_decision,
                agent_confidence = EXCLUDED.agent_confidence,
                report           = EXCLUDED.report,
                tokens_used      = COALESCE(EXCLUDED.tokens_used, vigil_cases.tokens_used),
                cost_inr         = COALESCE(EXCLUDED.cost_inr, vigil_cases.cost_inr),
                updated_at       = now()
            """,
            (
                case.get("case_id", "unknown"),
                case.get("customer", {}).get("name", "unknown"),
                json.dumps(case),
                typology,
                decision,
                confidence,
                report,
                tokens_used,
                cost_inr,
            ),
        )


def record_review(case_id: str, reviewer: str, action: str, rationale: str = "") -> dict:
    """
    Record the human decision. approve = accept the agent's call; override = invert it.

    Raises LookupError (unknown case) or ValueError (not yet investigated /
    bad action) — the API maps these to 404/400.
    """
    init_tables()
    if action not in VALID_REVIEW_ACTIONS:
        raise ValueError(f"action must be one of {VALID_REVIEW_ACTIONS}")

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT agent_decision FROM vigil_cases WHERE case_id = %s", (case_id,)
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"case '{case_id}' not found")
        agent_decision = row[0]
        if not agent_decision:
            raise ValueError("case has not been investigated yet")

        escalate = agent_decision == "ESCALATE"
        if action == "approve":
            final_status = "str_filed" if escalate else "dismissed"
        else:
            final_status = "dismissed" if escalate else "str_filed"

        cur.execute(
            """
            INSERT INTO vigil_reviews (case_id, reviewer, action, final_status, rationale)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (case_id, reviewer, action, final_status, rationale),
        )
        cur.execute(
            "UPDATE vigil_cases SET status = %s, updated_at = now() WHERE case_id = %s",
            (final_status, case_id),
        )

    return {"case_id": case_id, "final_status": final_status, "action": action}


def get_stats() -> dict:
    """Aggregate lifecycle counts for the dashboard band."""
    init_tables()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE status = 'flagged'),
                   count(*) FILTER (WHERE status = 'auto_dismissed'),
                   count(*) FILTER (WHERE status = 'in_review'),
                   count(*) FILTER (WHERE status = 'str_filed'),
                   count(*) FILTER (WHERE status = 'dismissed')
            FROM vigil_cases
            """
        )
        total, flagged, auto_dism, in_review, str_filed, dismissed = cur.fetchone()
        cur.execute("SELECT count(*) FROM vigil_reviews")
        reviews = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COALESCE(SUM(cost_inr), 0), COALESCE(AVG(cost_inr), 0), COUNT(*)
            FROM vigil_cases WHERE cost_inr IS NOT NULL
            """
        )
        spend, avg_cost, investigated = cur.fetchone()

    return {
        "total_cases": total,
        "flagged": flagged,
        "auto_dismissed": auto_dism,
        "in_review": in_review,
        "str_filed": str_filed,
        "dismissed": dismissed,
        "reviews_recorded": reviews,
        "noise_reduction_pct": round(auto_dism / total * 100, 1) if total else 0.0,
        # Triage economics: what was spent on LLM investigations, and what the
        # auto-dismissed cases would have cost at the same average rate.
        "investigated_with_llm": investigated,
        "llm_spend_inr": round(spend, 2),
        "avg_cost_per_investigation_inr": round(avg_cost, 2),
        "est_saved_by_triage_inr": round(auto_dism * avg_cost, 2),
    }


def list_cases(status: str | None = None, limit: int = 50) -> list[dict]:
    """Most-recent-first case list for the history view (no payload — keep it light)."""
    init_tables()
    where = "WHERE status = %s" if status else ""
    params: list = [status] if status else []
    params.append(limit)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT case_id, customer_name, risk_score, top_typology, status,
                   agent_decision, agent_confidence, updated_at
            FROM vigil_cases {where}
            ORDER BY updated_at DESC LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return [
        {
            "case_id": r[0],
            "customer_name": r[1],
            "risk_score": r[2],
            "top_typology": r[3],
            "status": r[4],
            "agent_decision": r[5],
            "agent_confidence": r[6],
            "updated_at": r[7].isoformat(),
        }
        for r in rows
    ]


def get_case(case_id: str) -> dict:
    """Full case record: payload, agent result, and its review audit trail."""
    init_tables()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT case_id, customer_name, payload, risk_score, top_typology, status,
                   agent_decision, agent_confidence, report, updated_at
            FROM vigil_cases WHERE case_id = %s
            """,
            (case_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"case '{case_id}' not found")
        cur.execute(
            """
            SELECT reviewer, action, final_status, rationale, created_at
            FROM vigil_reviews WHERE case_id = %s ORDER BY created_at
            """,
            (case_id,),
        )
        reviews = cur.fetchall()

    return {
        "case_id": row[0],
        "customer_name": row[1],
        "payload": row[2],
        "risk_score": row[3],
        "top_typology": row[4],
        "status": row[5],
        "agent_decision": row[6],
        "agent_confidence": row[7],
        "report": row[8],
        "updated_at": row[9].isoformat(),
        "reviews": [
            {
                "reviewer": r[0],
                "action": r[1],
                "final_status": r[2],
                "rationale": r[3],
                "created_at": r[4].isoformat(),
            }
            for r in reviews
        ],
    }
