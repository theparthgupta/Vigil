"""
LangGraph nodes for the Prahari agent (Phase 4).

Flow:  planner → investigator → reasoner → [conditional] → reporter
                      ↑__________________________|
                      (loop once if confidence < 0.6)

Each node takes PrahariState and returns only the keys it updates.
All LLM calls use gpt-4o-mini at temperature=0 for reproducibility.
"""

from __future__ import annotations

import os
from typing import Literal, Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from agent.prompts import (
    PLANNER_SYSTEM_PROMPT,
    REASONER_SYSTEM_PROMPT,
    REPORTER_SYSTEM_PROMPT,
)
from agent.state import PrahariState
from rag.retrieve import retrieve
from tools.media import search_adverse_media
from tools.patterns import analyze_patterns
from tools.profile import summarize_profile
from tools.sanctions import check_sanctions

load_dotenv()

_MODEL = "gpt-4o-mini"
_CONFIDENCE_THRESHOLD = 0.6
_MAX_PASSES = 2                       # original pass + at most one widened re-pass
_HIGH_VALUE_INR = 1_000_000          # ₹10L — names above this warrant adverse-media

ALL_TOOLS = ["profile", "patterns", "sanctions", "adverse_media"]


def _llm(temperature: float = 0.0) -> ChatOpenAI:
    return ChatOpenAI(model=_MODEL, temperature=temperature)


# ── Structured-output schemas ─────────────────────────────────────────────────

class ToolPlan(BaseModel):
    """Planner output: ordered tool names to run."""
    tools: list[str] = Field(
        description="Ordered subset of: profile, patterns, sanctions, adverse_media"
    )


class ReasonerOutput(BaseModel):
    """Reasoner decision."""
    decision: Literal["ESCALATE", "DISMISS"]
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the decision")
    typology: Optional[str] = Field(
        default=None,
        description="structuring | sanctions_hit | rapid_passthrough | None",
    )
    reasoning: str = Field(description="Concise reasoning grounded in evidence + regulation")
    key_evidence: list[str] = Field(description="The specific facts that drove the decision")


# ── 1. Planner ────────────────────────────────────────────────────────────────

def planner(state: PrahariState) -> dict:
    case = state["case"]
    summary = _case_summary(case)

    llm = _llm().with_structured_output(ToolPlan)
    plan = llm.invoke([
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": summary},
    ])

    # Keep only valid tool names, preserving the LLM's order; fall back to all tools
    tools = [t for t in plan.tools if t in ALL_TOOLS] or list(ALL_TOOLS)

    return {
        "tool_plan": tools,
        "investigation_steps": state["investigation_steps"]
        + [f"Planner: tool plan = {tools}"],
    }


def _case_summary(case: dict) -> str:
    cust = case["customer"]
    txns = case["transactions"]
    amounts = [t["amount_inr"] for t in txns]
    channels = {t["channel"] for t in txns}
    near_threshold = sum(1 for a in amounts if 800_000 <= a <= 999_999)
    over_threshold = sum(1 for a in amounts if a >= _HIGH_VALUE_INR)
    cash_credits = sum(
        1 for t in txns if t["channel"] == "cash" and t["direction"] == "credit"
    )
    return (
        f"Customer: {cust['name']} ({cust['business_type']}), "
        f"prior_flags={cust['prior_flags']}, "
        f"stated_monthly_turnover=Rs.{cust['stated_monthly_turnover_inr']/1e5:.1f}L.\n"
        f"Transactions: {len(txns)} total; channels={sorted(channels)}; "
        f"cash credits={cash_credits}; "
        f"deposits in Rs.8L-10L band={near_threshold}; "
        f"transactions >= Rs.10L={over_threshold}."
    )


# ── 2. Investigator ───────────────────────────────────────────────────────────

def investigator(state: PrahariState) -> dict:
    case = state["case"]
    txns = case["transactions"]
    plan = state["tool_plan"] or list(ALL_TOOLS)
    is_widen_pass = state["investigation_passes"] >= 1

    evidence = dict(state["evidence"])   # copy; merge so a re-pass augments, not replaces
    counterparties = sorted({t["counterparty_name"] for t in txns})

    if "profile" in plan:
        evidence["profile"] = summarize_profile(case["customer"])

    if "patterns" in plan:
        evidence["patterns"] = analyze_patterns(txns)

    if "sanctions" in plan:
        # 1st pass: screen all counterparties (cheap, local). Widen pass: same set
        # (already exhaustive) — kept for symmetry / future remote API throttling.
        hits = []
        for name in counterparties:
            res = check_sanctions(name)
            if res["is_match"]:
                hits.append(res)
        evidence["sanctions"] = {"hits": hits, "checked": len(counterparties)}

    if "adverse_media" in plan:
        if is_widen_pass:
            # Widen scope: screen every counterparty
            targets = counterparties
        else:
            # 1st pass: only sanctioned or high-value counterparties + the customer
            flagged = {h["name_queried"] for h in evidence.get("sanctions", {}).get("hits", [])}
            high_value = {
                t["counterparty_name"] for t in txns if t["amount_inr"] >= _HIGH_VALUE_INR
            }
            targets = sorted(flagged | high_value | {case["customer"]["name"]})
        evidence["adverse_media"] = {
            name: search_adverse_media(name) for name in targets
        }

    pass_label = "widened re-pass" if is_widen_pass else "initial pass"
    return {
        "evidence": evidence,
        "investigation_passes": state["investigation_passes"] + 1,
        "investigation_steps": state["investigation_steps"]
        + [f"Investigator ({pass_label}): ran {plan}; "
           f"{len(evidence.get('sanctions', {}).get('hits', []))} sanctions hit(s)"],
    }


# ── 3. Reasoner ───────────────────────────────────────────────────────────────

def reasoner(state: PrahariState) -> dict:
    evidence = state["evidence"]
    queries = _build_queries(evidence)

    passages, seen = [], set()
    for q in queries:
        for p in retrieve(q, k=4):
            key = (p["source"], p["section"], p["page"])
            if key not in seen:
                seen.add(key)
                passages.append(p)

    user_msg = _reasoner_user_message(state["case"], evidence, passages)
    llm = _llm().with_structured_output(ReasonerOutput)
    out: ReasonerOutput = llm.invoke([
        {"role": "system", "content": REASONER_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])

    return {
        "retrieved_passages": passages,
        "decision": out.decision,
        "confidence": out.confidence,
        "investigation_steps": state["investigation_steps"]
        + [f"Reasoner: {out.decision} (confidence={out.confidence:.2f}, "
           f"typology={out.typology}) — {out.reasoning[:160]}"],
    }


def _build_queries(evidence: dict) -> list[str]:
    """Typology-driven RAG queries; always include the STR filing obligation."""
    queries = ["suspicious transaction reporting obligation STR filing PMLA"]
    patterns = evidence.get("patterns", {})
    if patterns.get("structuring_indicator", {}).get("flagged"):
        queries.append("structuring cash transaction reporting CTR threshold ten lakh")
    if patterns.get("rapid_passthrough_indicator", {}).get("flagged"):
        queries.append("layering rapid movement of funds suspicious transaction")
    if evidence.get("sanctions", {}).get("hits"):
        queries.append("sanctions screening politically exposed person enhanced due diligence")
    return queries


def _reasoner_user_message(case: dict, evidence: dict, passages: list[dict]) -> str:
    cust = case["customer"]
    pat = evidence.get("patterns", {})
    san = evidence.get("sanctions", {})
    prof = evidence.get("profile", {})

    lines = [
        "CASE UNDER REVIEW",
        f"Customer: {cust['name']} ({cust['business_type']}), prior_flags={cust['prior_flags']}",
        f"Profile risk: {prof.get('risk_level', 'n/a')} — {prof.get('summary', '')}",
        "",
        "PRE-COMPUTED TRANSACTION FEATURES (do not recompute):",
        f"  total_transactions: {pat.get('total_transactions')}",
        f"  cash_credit_total_inr: {pat.get('cash_credit_total_inr')}",
        f"  structuring_indicator: {pat.get('structuring_indicator')}",
        f"  rapid_passthrough_indicator: {pat.get('rapid_passthrough_indicator')}",
        f"  velocity_30d: {pat.get('velocity_30d')}, "
        f"counterparty_diversity_ratio: {pat.get('counterparty_diversity_ratio')}",
        "",
        f"SANCTIONS SCREENING: {len(san.get('hits', []))} hit(s) "
        f"out of {san.get('checked', 0)} counterparties checked.",
    ]
    for h in san.get("hits", []):
        lines.append(f"  - {h['name_queried']} matched {h['matched_entity']} "
                     f"(score {h['match_score']})")

    lines += ["", "RETRIEVED REGULATORY PASSAGES (cite these by source + section + page):"]
    for i, p in enumerate(passages, 1):
        lines.append(f"[{i}] {p['citation']} | {p['section']} | p.{p['page']}")
        lines.append(f"    {p['text'][:500].strip()}")

    lines += ["", "Decide ESCALATE or DISMISS with confidence and grounded reasoning."]
    return "\n".join(lines)


# ── 4. Reporter ───────────────────────────────────────────────────────────────

def reporter(state: PrahariState) -> dict:
    user_msg = _reporter_user_message(state)
    out = _llm().invoke([
        {"role": "system", "content": REPORTER_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])
    report = out.content if hasattr(out, "content") else str(out)
    return {
        "report": report,
        "investigation_steps": state["investigation_steps"]
        + [f"Reporter: STR-format report generated ({len(report)} chars)"],
    }


def _reporter_user_message(state: PrahariState) -> str:
    case = state["case"]
    cust = case["customer"]
    evidence = state["evidence"]
    pat = evidence.get("patterns", {})
    san = evidence.get("sanctions", {})

    lines = [
        f"DECISION: {state['decision']} (confidence {state['confidence']:.2f})",
        "",
        f"CUSTOMER: {cust['name']} | {cust['business_type']} | "
        f"prior_flags={cust['prior_flags']} | "
        f"stated_monthly_turnover=Rs.{cust['stated_monthly_turnover_inr']/1e5:.1f}L",
        "",
        "TRANSACTION FEATURES (use these figures verbatim):",
        f"  {pat.get('total_transactions')} transactions; "
        f"cash credits total Rs.{pat.get('cash_credit_total_inr', 0)/1e5:.1f}L",
        f"  structuring: {pat.get('structuring_indicator')}",
        f"  rapid_passthrough: {pat.get('rapid_passthrough_indicator')}",
        f"  sanctions hits: {san.get('hits', [])}",
        "",
        "REGULATORY PASSAGES (cite by source + section/rule + page):",
    ]
    for i, p in enumerate(state["retrieved_passages"], 1):
        lines.append(f"[{i}] {p['citation']} | {p['section']} | p.{p['page']}")
        lines.append(f"    {p['text'][:400].strip()}")

    lines += ["", "Draft the STR-format report using the five mandated sections."]
    return "\n".join(lines)


# ── Conditional edge ──────────────────────────────────────────────────────────

def route_after_reasoner(state: PrahariState) -> Literal["investigate", "report"]:
    """Loop back for one widened evidence pass if confidence is low."""
    if (
        state["confidence"] < _CONFIDENCE_THRESHOLD
        and state["investigation_passes"] < _MAX_PASSES
    ):
        return "investigate"
    return "report"
