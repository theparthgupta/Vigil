"""
Run the Vigil agent end-to-end on ONE case from the TRAIN split.

Usage:
    python agent/run_one.py            # default: first structuring case
    python agent/run_one.py 12         # case at index 12 in cases_train.json

Prints the decision, confidence, audit trail, STR report, and the LangSmith
trace URL. NEVER reads cases_holdout.json (locked until Phase 5 final eval).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from langchain_core.tracers.context import collect_runs

from agent.graph import graph
from agent.state import initial_state

load_dotenv()

_TRAIN = Path(__file__).parent.parent / "data" / "cases_train.json"


def _trace_url(run) -> str:
    """Best-effort LangSmith trace URL for a captured run."""
    # Newer langsmith RunTree exposes .url; otherwise build from the LangSmith client.
    url = getattr(run, "url", None)
    if url:
        return url
    try:
        from langsmith import Client

        return Client().get_run_url(run=run)
    except Exception as exc:  # noqa: BLE001 — diagnostics only
        return f"(could not resolve trace URL: {exc}; run_id={getattr(run, 'id', '?')})"


def main(index: int = 0) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cases = json.loads(_TRAIN.read_text(encoding="utf-8"))

    # Default: first structuring case (clear, interpretable typology)
    if index == 0:
        index = next((i for i, c in enumerate(cases) if c["typology"] == "structuring"), 0)
    case = cases[index]

    print(
        f"Running case #{index}: {case['case_id']} "
        f"(ground truth: {case['ground_truth_label']} / {case['typology']})"
    )
    print("=" * 72)

    with collect_runs() as cb:
        result = graph.invoke(initial_state(case))

    print("\n--- AUDIT TRAIL ---")
    for step in result["investigation_steps"]:
        print(f"  • {step}")

    print(f"\n--- DECISION ---\n{result['decision']} (confidence {result['confidence']:.2f})")
    print(f"Ground truth: {case['ground_truth_label']} / {case['typology']}")

    print(f"\n--- RETRIEVED PASSAGES ({len(result['retrieved_passages'])}) ---")
    for p in result["retrieved_passages"]:
        print(f"  [{p['citation']} | {p['section']} | p.{p['page']}]")

    print("\n--- STR REPORT ---")
    print(result["report"])

    print("\n--- LANGSMITH TRACE ---")
    if cb.traced_runs:
        print(_trace_url(cb.traced_runs[0]))
    else:
        print("(no runs captured — check LANGSMITH_TRACING in .env)")


if __name__ == "__main__":
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    main(idx)
