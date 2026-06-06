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

---
### 2026-06-07 — Phase 3: RAG pipeline (section-boundary chunking + Chroma)
**What changed:** `rag/ingest.py` (PDF extraction, section-boundary chunking, OpenAI embedding, Chroma persistence); `rag/retrieve.py` (cosine-similarity retrieval with citation metadata); `tests/test_rag.py` (8 tests); `pypdf` added to `requirements.txt`; `rag/chroma_db/` (gitignored, 893 chunks from 4 documents).
**Why:** The LangGraph Reasoner node needs citable regulatory passages to ground its decisions. Without RAG, the LLM would hallucinate PMLA section numbers and RBI circular references.
**What this is:** A retrieval-augmented generation (RAG) pipeline: PDFs are chunked into semantically coherent sections, embedded with `text-embedding-3-small` (1536-dim), stored in a Chroma vector store, and queried by cosine similarity at inference time. Section-boundary chunking (regex on PMLA/RBI/APG heading patterns) keeps related legal text together rather than breaking mid-clause.
**Why it matters here:** Indian legal documents use inconsistent numbering schemes (PMLA: "12AA."; RBI: "Chapter IV –"; APG: "2.4"). Fixed-size splitting would fragment references like "Section 12AA(1)(b) of the PMLA" across chunks, making citations unretrievable. Metadata (source, section header, page) on every chunk enables the Reasoner to emit precise citations like "RBI KYC MD 2025, para 45, p.46".
**Drawbacks / risks:** The 7-day STR filing timeline (PMLA Maintenance of Records Rules 2005, Rule 3) is NOT in the corpus — those subsidiary rules were not provided as PDFs. The Reasoner will need to note this gap rather than hallucinate the deadline. FIU-IND Reporting Format document capped at page 23 (pages 24+ are pure schema tables that pollute retrieval with field-definition noise). Schema-table filter (>55% short lines) catches residual table chunks.
**Alternatives considered:** LangChain `RecursiveCharacterTextSplitter` (rejected — splits by char count without legal-section awareness; tested and produced many mid-clause breaks); `langchain-community` Chroma integration (rejected — adds a heavy package; raw chromadb + OpenAIEmbeddings is sufficient and more transparent); fixed 512-token chunks with 128-token overlap (rejected — breaks across section numbers, wrecking citation quality).
**How to verify:** `pytest tests/test_rag.py -v` → 8 passed. `python rag/retrieve.py` → Q1 returns RBI KYC Chapter VIII (CTR/STR obligations); Q2 returns RBI para 54 (reporting time limit reference) at rank 3 — exact 7-day text is missing from corpus (data gap); Q3 returns RBI KYC para 45 (PEP definition) at score 0.564.
---

---
### 2026-06-07 — Phase 3 addendum: PMLA Rules 2005 ingested + STR-deadline correction
**What changed:** Added 5th document `PMLA_Rules.pdf` (PMLA Maintenance of Records Rules 2005, G.S.R. 444(E)) to the ingest registry → 35 chunks (corpus now 928 total). Fixed a run-on-text chunking bug. Created `agent/prompts.py` with the Reasoner system prompt + STR-deadline guidance. Corrected constraint #1 in ROADMAP.md (two locations).
**Why:** The 7-day STR deadline was the original premise for ingesting this document. On inspection, the document proves the opposite — the current statutory STR deadline is "promptly", not 7 days — a material accuracy issue for an AML product whose generated reports cite legal deadlines.
**What this is:** The PMLA (Maintenance of Records) Rules 2005 are the subsidiary legislation under PMLA 2002 that set reporting deadlines. Rule 8(2), as amended in 2015 (gazette marker `35[...]`), reads: "...on being satisfied that the transaction is suspicious, furnish the information **promptly**...". The original 2005 Rule 8(2) said "not later than seven working days"; the amendment deleted it. The only "seven days" remaining in the document is Rule 9(1D), which governs KYC record updates to CKYCR — not STR filing.
**Why it matters here:** Constraint #1 ("STR filed within 7 days") would have made the Reasoner cite a non-existent statutory deadline — exactly the kind of error a compliance officer catches instantly. Resolution (user-approved Option 2): treat "promptly" as the statutory requirement (cite Rule 8(2) verbatim) and 7 working days as a labelled industry norm / internal SLA. CTR deadline is monthly by the 15th of the succeeding month (Rule 8(1)).
**Drawbacks / risks:** This corpus uses the *current* (amended) Rules; historical cases filed under the pre-2015 7-day regime would need the original text, which is not included. The run-on-chunking heuristic (newline-density < 0.005 → split on inline rule headers) is tuned to this gazette's extraction style and may need adjustment for other run-on PDFs.
**Alternatives considered:** Keep "7 days" as the stated deadline (rejected — factually wrong under current law); drop the 7-day figure entirely (rejected — it is a real, widely-used industry SLA worth surfacing, just not as statute); re-chunk all 5 docs with a unified inline splitter (rejected — the other 4 chunk correctly with line-anchored regex; surgical run-on branch avoids regressions).
**How to verify:** `python rag/ingest.py` (incremental) adds 35 PMLA_Rules chunks. Source-filtered retrieve for Rule 8 returns citation "PMLA (Maintenance of Records) Rules, 2005, 8.Furnishing of information to the Director, p.9" with the verbatim "promptly" text at score 0.62. `agent/prompts.py` STR_DEADLINE_GUIDANCE encodes the statutory-vs-norm distinction.
---
