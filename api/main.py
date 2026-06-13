"""
FastAPI backend for Vigil (Phase 6).

Serves the single-page UI (app/static) and the agent API.

Endpoints:
    GET  /            — Vigil web UI (static SPA)
    GET  /health      — liveness check
    GET  /sample      — one random case from the TRAIN split (for the UI to load)
    POST /investigate — run a case through the LangGraph agent, return the decision

Run: uvicorn api.main:app --reload
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.graph import graph
from agent.state import initial_state
from data.schema import Case

load_dotenv()

_ROOT = Path(__file__).parent.parent
_TRAIN = _ROOT / "data" / "cases_train.json"
_STATIC = _ROOT / "app" / "static"

app = FastAPI(
    title="Vigil AML Investigation API",
    description="Autonomous AML triage agent for Indian financial institutions (PMLA/FIU-IND).",
    version="1.0.0",
)


@app.get("/")
def index() -> FileResponse:
    """Serve the Vigil single-page UI."""
    return FileResponse(_STATIC / "index.html")


class InvestigateResponse(BaseModel):
    case_id: str
    decision: str
    confidence: float
    detected_typology: str
    report: str
    investigation_steps: list[str]
    latency_seconds: float


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "vigil-api"}


@app.get("/sample")
def sample() -> dict:
    """Return one random TRAIN case so the UI has something to load instantly."""
    cases = json.loads(_TRAIN.read_text(encoding="utf-8"))
    return random.choice(cases)


@app.post("/investigate", response_model=InvestigateResponse)
def investigate(case: Case) -> InvestigateResponse:
    """Run a single case through the agent and return the decision + report."""
    case_dict = json.loads(case.model_dump_json())

    t0 = time.perf_counter()
    result = graph.invoke(
        initial_state(case_dict),
        config={"tags": ["api"], "run_name": f"api-{case.case_id}"},
    )
    latency = time.perf_counter() - t0

    return InvestigateResponse(
        case_id=case.case_id,
        decision=result["decision"],
        confidence=round(result["confidence"], 4),
        detected_typology=result.get("detected_typology", ""),
        report=result["report"],
        investigation_steps=result["investigation_steps"],
        latency_seconds=round(latency, 2),
    )


# ── Streaming investigation (Server-Sent Events) ──────────────────────────────
# Emits per-node progress as the LangGraph agent runs, so the UI can show each
# node firing in real time instead of freezing on a ~25s synchronous call.

_RUNNING_MSG = {
    "planner": "Planning the investigation…",
    "investigator": "Gathering evidence: sanctions, patterns, profile…",
    "reasoner": "Reasoning against PMLA / RBI regulation…",
    "reporter": "Drafting the Suspicious Transaction Report…",
}
_ORDER = ["planner", "investigator", "reasoner", "reporter"]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _done_message(node: str, delta: dict, final: dict) -> str:
    """Human-readable 'what this node just did' line, built from the state delta."""
    if node == "planner":
        return "Planner selected tools: " + ", ".join(delta.get("tool_plan", []))
    if node == "investigator":
        san = final.get("evidence", {}).get("sanctions", {})
        hits = len(san.get("hits", []))
        ran = list(final.get("evidence", {}).keys())
        return (f"Evidence gathered. Sanctions: {hits} hit(s) of "
                f"{san.get('checked', 0)} screened; ran {', '.join(ran)}")
    if node == "reasoner":
        # name the regulatory sources actually read
        srcs, seen = [], set()
        for p in final.get("retrieved_passages", []):
            short = p["citation"].split(" (")[0]
            if short not in seen:
                seen.add(short)
                srcs.append(short)
        src_str = "; ".join(srcs[:3]) if srcs else "regulatory corpus"
        conf = int(round(delta.get("confidence", 0.0) * 100))
        return f"Read {src_str} → {delta.get('decision', '?')} ({conf}% confidence)"
    if node == "reporter":
        return f"STR drafted ({len(delta.get('report', ''))} characters)"
    return node


@app.post("/investigate/stream")
def investigate_stream(case: Case) -> StreamingResponse:
    """Run the agent and stream per-node progress as SSE, ending with the result."""
    case_dict = json.loads(case.model_dump_json())

    def gen():
        t0 = time.perf_counter()
        final: dict = {}
        # announce the first node as "running"
        yield _sse("status", {"stage": "planner", "message": _RUNNING_MSG["planner"]})

        for update in graph.stream(
            initial_state(case_dict),
            config={"tags": ["api", "stream"], "run_name": f"api-stream-{case.case_id}"},
            stream_mode="updates",
        ):
            for node, delta in update.items():
                final.update(delta)
                if node in _ORDER:
                    yield _sse("node", {"node": node, "message": _done_message(node, delta, final)})
                    idx = _ORDER.index(node)
                    if idx < len(_ORDER) - 1:
                        nxt = _ORDER[idx + 1]
                        yield _sse("status", {"stage": nxt, "message": _RUNNING_MSG[nxt]})

        yield _sse("done", {
            "case_id": case.case_id,
            "decision": final.get("decision", ""),
            "confidence": round(final.get("confidence", 0.0), 4),
            "detected_typology": final.get("detected_typology", ""),
            "report": final.get("report", ""),
            "investigation_steps": final.get("investigation_steps", []),
            "latency_seconds": round(time.perf_counter() - t0, 2),
        })

    return StreamingResponse(gen(), media_type="text/event-stream")


# Static assets (styles.css, app.js). Mounted last so it never shadows API routes.
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
