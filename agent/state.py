"""
Shared state for the Vigil LangGraph agent (Phase 4).

LangGraph passes this dict between nodes. Each node returns a partial dict of
the keys it updates; LangGraph merges them into the running state.
"""

from __future__ import annotations

from typing import TypedDict


class VigilState(TypedDict):
    # Input
    case: dict  # loaded Case (customer + transactions + labels)

    # Gathered by Investigator
    evidence: dict  # {profile, patterns, sanctions, adverse_media}

    # Gathered by Reasoner
    retrieved_passages: list[dict]  # RAG hits: text + citation + source + section + page + score

    # Produced by Reasoner
    decision: str  # "ESCALATE" | "DISMISS" | "" (empty until reasoned)
    confidence: float  # 0.0–1.0
    detected_typology: str  # reasoner's typology label ("" if none / DISMISS)

    # Produced by Reporter
    report: str  # FIU-IND STR-format report

    # Audit trail — appended by every node
    investigation_steps: list[str]

    # Control fields (not in the original 7-field spec; required for orchestration)
    tool_plan: list[str]  # Planner's chosen tool order
    investigation_passes: int  # bounds the conditional loop to ONE extra pass


def initial_state(case: dict, detection_result: dict | None = None) -> VigilState:
    """
    Build a fresh state for a single case.

    If `detection_result` is given (the case already cleared the monitor triage
    gate via /detect or the triage queue), it is stashed at
    evidence["pre_screening"] so the Investigator can skip redundant tool calls.
    """
    evidence: dict = {}
    if detection_result is not None:
        evidence["pre_screening"] = detection_result
    return VigilState(
        case=case,
        evidence=evidence,
        retrieved_passages=[],
        decision="",
        confidence=0.0,
        detected_typology="",
        report="",
        investigation_steps=[],
        tool_plan=[],
        investigation_passes=0,
    )
