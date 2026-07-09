"""
Phase 11 cost-tracking tests (agent/costing.py + store cost columns).

The handler is fed synthetic LLM results — no OpenAI calls. Cost math is
pure Python against the published gpt-4o-mini price table.
"""

import uuid

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from agent.costing import USD_INR, TokenUsageHandler
from api.store import _connect, get_stats, init_tables, save_investigation

_PFX = "t11c_" + uuid.uuid4().hex[:8]


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    init_tables()
    yield
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM vigil_cases WHERE case_id LIKE %s", (_PFX + "%",))


def _fake_result(input_tokens: int, output_tokens: int) -> LLMResult:
    msg = AIMessage(
        content="x",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )
    return LLMResult(generations=[[ChatGeneration(message=msg)]])


# ── 1. Handler accumulates across calls ───────────────────────────────────────


def test_handler_accumulates():
    h = TokenUsageHandler()
    h.on_llm_end(_fake_result(1000, 200))
    h.on_llm_end(_fake_result(2000, 300))
    s = h.summary()
    assert s["llm_calls"] == 2
    assert s["input_tokens"] == 3000
    assert s["output_tokens"] == 500
    assert s["total_tokens"] == 3500


# ── 2. Cost math is exact (deterministic Python, no LLM) ──────────────────────


def test_cost_math_exact():
    h = TokenUsageHandler()
    h.on_llm_end(_fake_result(1_000_000, 1_000_000))  # 1M in + 1M out
    s = h.summary()
    assert s["cost_usd"] == round(0.15 + 0.60, 6)  # $0.75
    assert s["cost_inr"] == round(0.75 * USD_INR, 4)


# ── 3. Zero usage → zero cost ─────────────────────────────────────────────────


def test_zero_usage():
    s = TokenUsageHandler().summary()
    assert s["total_tokens"] == 0
    assert s["cost_inr"] == 0.0


# ── 4. Cost persists on the case and rolls into stats ─────────────────────────


def test_cost_persists_and_stats_roll_up():
    case = {"case_id": f"{_PFX}_a", "customer": {"name": "Cost Test"}, "transactions": []}
    save_investigation(
        case, "ESCALATE", 0.9, "structuring", "STR", tokens_used=12345, cost_inr=1.23
    )

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT tokens_used, cost_inr FROM vigil_cases WHERE case_id = %s", (f"{_PFX}_a",)
        )
        tokens, cost = cur.fetchone()
    assert tokens == 12345
    assert cost == 1.23

    stats = get_stats()
    for key in (
        "llm_spend_inr",
        "avg_cost_per_investigation_inr",
        "est_saved_by_triage_inr",
        "investigated_with_llm",
    ):
        assert key in stats
    assert stats["investigated_with_llm"] >= 1
    assert stats["llm_spend_inr"] >= 1.23
