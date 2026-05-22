# DECISIONS.md

The project's narrative. One entry per meaningful change — what it is, why, the
tradeoffs, and how to verify. Append-only and chronological. Maintained by the
`explain-change` skill. Newest entries at the bottom.

---
### <YYYY-MM-DD> — Project scaffolding + Claude Code rules
**What changed:** Added CLAUDE.md, the `explain-change` skill, and this log.
**Why:** Start the project with explicit working rules and a durable record of
decisions, so it stays understandable as it grows.
**What this is:** CLAUDE.md is a file Claude Code reads at the start of every
conversation; skills are on-demand instruction sets loaded only when relevant.
**Why it matters here:** Sets the contract before any code exists — caution over
speed, surgical edits, verify-by-test, and a written rationale for every change.
**Drawbacks / risks:** Slight overhead per task; the discipline only pays off if the
log is actually kept up to date.
**Alternatives considered:** No rules file (rejected — repeats context every session);
one giant CLAUDE.md with everything (rejected — bloated files get ignored).
**How to verify:** Run `/init` related checks pass and Claude follows the rules on the
first real task.
---

---
### 2026-05-22 — Phase 0: repo scaffold, venv, dependencies, directory layout
**What changed:** `git init`; Python 3.14 venv; `requirements.txt` (langgraph, langchain, langchain-anthropic, chromadb, fastapi, uvicorn, streamlit, pydantic, pandas, scikit-learn, python-dotenv, langsmith, httpx, requests); 8 package directories with `__init__.py` (`data/`, `tools/`, `rag/`, `agent/`, `eval/`, `api/`, `app/`, `regs/`); `.env.example`; `.gitignore`; `README.md`; Commands section of CLAUDE.md filled in.
**Why:** Phase 0 of ROADMAP — lay the foundation before any code so every subsequent session has a clean, importable package layout and every run is traced in LangSmith from day one.
**What this is:** A Python venv isolates project dependencies from the system interpreter; `__init__.py` makes each directory a proper package so `from agent.graph import ...` style imports work without path hacks.
**Why it matters here:** LangGraph, LangSmith, and Chroma all have overlapping dependency trees. Pinning to a venv now prevents version conflicts in Phases 1-4 and makes the Render deploy deterministic.
**Drawbacks / risks:** `opensanctions` PyPI package dropped — it pulls in `pyicu` (ICU C library), which can't be built on Windows without additional tooling. The OpenSanctions `/match` endpoint is plain REST; `httpx` (already in deps) is sufficient for Phase 2.
**Alternatives considered:** conda (rejected — venv is lighter and the Render deploy target uses pip); poetry (rejected — adds lock-file complexity before any real code exists, can revisit for packaging in Phase 7).
**How to verify:** `pip install -r requirements.txt` completes without errors; `python -c "import langgraph, langchain_anthropic, chromadb, langsmith"` exits 0.
---
