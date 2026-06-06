"""
Shared state for the Prahari LangGraph agent (Phase 4).

LangGraph passes this dict between nodes. Each node returns a partial dict of
the keys it updates; LangGraph merges them into the running state.
"""

from __future__ import annotations

from typing import TypedDict


class PrahariState(TypedDict):
    # Input
    case: dict                       # loaded Case (customer + transactions + labels)

    # Gathered by Investigator
    evidence: dict                   # {profile, patterns, sanctions, adverse_media}

    # Gathered by Reasoner
    retrieved_passages: list[dict]   # RAG hits: text + citation + source + section + page + score

    # Produced by Reasoner
    decision: str                    # "ESCALATE" | "DISMISS" | "" (empty until reasoned)
    confidence: float                # 0.0–1.0

    # Produced by Reporter
    report: str                      # FIU-IND STR-format report

    # Audit trail — appended by every node
    investigation_steps: list[str]

    # Control fields (not in the original 7-field spec; required for orchestration)
    tool_plan: list[str]             # Planner's chosen tool order
    investigation_passes: int        # bounds the conditional loop to ONE extra pass


def initial_state(case: dict) -> PrahariState:
    """Build a fresh state for a single case."""
    return PrahariState(
        case=case,
        evidence={},
        retrieved_passages=[],
        decision="",
        confidence=0.0,
        report="",
        investigation_steps=[],
        tool_plan=[],
        investigation_passes=0,
    )
