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
from fastapi.responses import FileResponse
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


# Static assets (styles.css, app.js). Mounted last so it never shadows API routes.
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
