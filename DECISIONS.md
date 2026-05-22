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

---
### 2026-05-23 — Phase 1: synthetic AML dataset (schema + generator)
**What changed:** `data/schema.py` (5 Pydantic models: TransactionRecord, CustomerProfile, Case, plus enums for BusinessType, Direction, Channel, Label, Typology); `data/generator.py` (200 deterministic cases, seed=42); `data/cases_train.json` (160 cases); `data/cases_holdout.json` (40 cases, locked); `data/README.md`.
**Why:** The eval-first principle from the ROADMAP — without a labeled dataset there is nothing to measure, and without a metric there is no basis for any design decision in Phases 2–5.
**What this is:** A seeded Python random generator that produces four typologies of synthetic bank transaction cases (structuring, sanctions hit, rapid passthrough, clean) with Pydantic-validated schemas. Each case carries a ground-truth label and a human-readable notes field explaining the label.
**Why it matters here:** Structuring thresholds are India-specific (CTR = Rs.10 lakh, PMLA s.12). Sanctions names are placeholders for the OpenSanctions /match API (Phase 2 Tool 1). Rapid-passthrough uses the 72h/80% definition consistent with FATF South Asia typology reports. The holdout split is locked so Phase 5 eval numbers are not contaminated by prompt tuning.
**Drawbacks / risks:** 75/25 suspicious-to-clean ratio (3 suspicious typologies, 1 clean) — a naive classifier that always predicts suspicious achieves 75% accuracy. FPR on clean cases must be reported explicitly or the benchmark is misleading. Synthetic data also cannot capture real-world noise (OCR errors, name transliterations, incomplete records).
**Alternatives considered:** 50/50 balance (rejected — would require cutting one suspicious typology or doubling clean cases; 50 clean cases is enough to measure FPR meaningfully); real transaction data (rejected — non-public, PMLA data localisation rules, can't be shared in a public repo); Faker library for names (rejected — adds a dependency for something trivially done with hardcoded lists, and Faker's Indian locale is incomplete).
**How to verify:** `python data/generator.py` exits 0, prints 160 train / 40 holdout, both JSON files pass the structural check script (all required fields, correct counts, labels sane). Re-running produces byte-identical output.
---

---
### 2026-05-23 — Phase 2: tool layer (4 investigative tools + 35 tests)
**What changed:** `tools/sanctions.py`, `tools/patterns.py`, `tools/media.py`, `tools/profile.py`; `tests/conftest.py` + 4 test files (35 tests); `pyproject.toml` (pytest + ruff + mypy config); `requirements-dev.txt`.
**Why:** The LangGraph agent (Phase 4) calls these tools to gather evidence. Building and testing them in isolation now means the agent wires together verified components rather than debugging tool logic and orchestration simultaneously.
**What this is:** Four pure Python functions returning plain JSON-serialisable dicts. Tool 1 screens names against sanctions lists (OpenSanctions REST API with local fuzzy-match fallback). Tool 2 extracts AML features deterministically (structuring window, passthrough ratio, velocity, counterparty diversity). Tool 3 searches adverse media via DuckDuckGo Instant Answer API (no key required; stable interface for future swap). Tool 4 structures customer risk facts (business type, account age, prior flags) into a rated summary.
**Why it matters here:** All arithmetic lives in Tool 2 — the LLM Reasoner receives pre-computed features, not raw transactions, so it cannot hallucinate transaction amounts or counts. Tools 1/3/4 are the evidence-gathering layer; the agent's Reasoner synthesises them against RAG-retrieved regulations. Keeping tools as plain dicts (not Pydantic) avoids serialisation friction inside LangGraph state.
**Drawbacks / risks:** Tool 3 (adverse media) uses DuckDuckGo's unofficial instant-answer API — no guaranteed SLA, results are thin for non-public figures. Structuring band uses Rs.8L as lower bound (not Rs.9L) to catch synthetic cases generated from Rs.8.5L; real deployment should recalibrate against actual bank data. Fuzzy-match threshold (0.6) for local sanctions screening may produce false positives on similar-sounding names.
**Alternatives considered:** LLM-based pattern detection for Tool 2 (rejected — violates CLAUDE.md rule: LLM does not do arithmetic); Pydantic return types for tools (rejected — adds coupling; plain dicts flow directly into LangGraph state JSON); Serper API for Tool 3 (rejected — requires paid key; DuckDuckGo is sufficient for a portfolio demo).
**How to verify:** `pytest tests/ -v` → 35 passed. Each suspicious-typology case fires the correct detector; each clean case fires nothing. Sanctions hits found in every sanctions_hit train case; zero hits in clean cases.
---
